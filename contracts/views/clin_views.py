from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import DetailView, UpdateView, CreateView
from django.contrib import messages
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, HttpResponseRedirect, Http404, HttpResponseForbidden
from django.template.loader import render_to_string
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from datetime import timedelta, datetime, time
import json
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

from STATZWeb.decorators import conditional_login_required
from ..models import Clin, ClinAcknowledgment, ClinShipment, Contract, Note, Reminder, Nsn, Supplier
from .mixins import ActiveCompanyQuerysetMixin
from ..forms import ClinForm, ClinAcknowledgmentForm
from .note_views import annotate_notes_for_current_user


@method_decorator(conditional_login_required, name='dispatch')
class ClinDetailView(ActiveCompanyQuerysetMixin, DetailView):
    model = Clin
    template_name = 'contracts/clin_detail.html'
    context_object_name = 'clin'

    def get_queryset(self):
        company = self.get_active_company()
        return Clin.objects.select_related(
            'contract',
            'clin_type',
            'supplier',
            'nsn',
            'special_payment_terms',
            'created_by',
            'modified_by',
        ).prefetch_related('splits').filter(company=company)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        clin = self.object

        # Add notes to context
        clin_type = ContentType.objects.get_for_model(Clin)
        notes = Note.objects.filter(
            content_type=clin_type,
            object_id=clin.id
        ).order_by('-created_on')
        context['notes'] = notes

        # Add acknowledgment data
        try:
            acknowledgment = ClinAcknowledgment.objects.get(clin=clin)
            context['acknowledgment'] = acknowledgment
        except ClinAcknowledgment.DoesNotExist:
            context['acknowledgment'] = None

        context['clin_content_type_id'] = ContentType.objects.get_for_model(Clin).id
        context['clinshipment_content_type_id'] = ContentType.objects.get_for_model(ClinShipment).id
        context['clin_splits'] = clin.splits.all()
        return context


@method_decorator(conditional_login_required, name='dispatch')
class ClinCreateView(ActiveCompanyQuerysetMixin, CreateView):
    model = Clin  # Using the actual Clin model, not the view
    form_class = ClinForm
    template_name = 'contracts/clin_form.html'
    
    def get_initial(self):
        initial = super().get_initial()
        contract_id = self.kwargs.get('contract_id')
        if contract_id:
            contract_data = Contract.objects.filter(company=self.request.active_company).select_related('idiq_contract', 'status').get(id=contract_id)
            initial['contract'] = contract_id
            initial['contract_number'] = contract_data.contract_number
            initial['po_number'] = contract_data.po_number
            initial['tab_num'] = contract_data.tab_num
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contract_id = self.kwargs.get('contract_id')
        if contract_id:
            company = getattr(self.request, 'active_company', None)
            qs = Clin.objects.filter(
                contract_id=contract_id,
                contract__company=company,
            ).select_related('supplier', 'nsn').order_by('item_number')
            context['copy_from_clins'] = list(qs) if qs.exists() else []
        else:
            context['copy_from_clins'] = []
        return context
    
    def form_valid(self, form):
        # Debugging information
        print("Form data:", self.request.POST)
        print("NSN ID:", self.request.POST.get('nsn'))
        print("Supplier ID:", self.request.POST.get('supplier'))
        print("Contract ID:", self.request.POST.get('contract'))
        
        # Explicitly ensure we're working with a Clin instance
        self.object = form.save(commit=False)
        contract_id = self.kwargs.get('contract_id') or self.request.POST.get('contract')
        
        # Verify that NSN and Supplier objects exist before saving
        nsn_id = self.request.POST.get('nsn')
        supplier_id = self.request.POST.get('supplier')
        
        try:
            # Get the actual Nsn and Supplier objects to verify they exist
            if nsn_id:
                nsn_obj = Nsn.objects.get(pk=nsn_id)
                # Explicitly set the nsn on the Clin instance
                self.object.nsn = nsn_obj
            else:
                form.add_error('nsn', 'NSN is required')
                return self.form_invalid(form)
                
            if supplier_id:
                supplier_obj = Supplier.objects.get(pk=supplier_id)
                # Explicitly set the supplier on the Clin instance
                self.object.supplier = supplier_obj
            else:
                form.add_error('supplier', 'Supplier is required')
                return self.form_invalid(form)

            if not self.object.contract_id:
                if contract_id:
                    contract_qs = Contract.objects
                    if getattr(self.request, 'active_company', None):
                        contract_qs = contract_qs.filter(company=self.request.active_company)
                    self.object.contract = contract_qs.get(id=contract_id)
                else:
                    form.add_error('contract', 'Contract is required')
                    return self.form_invalid(form)
                
            # Set the created_by and modified_by fields
            self.object.created_by = self.request.user
            self.object.modified_by = self.request.user
            if not self.object.company_id:
                if getattr(self.object, 'contract', None) and self.object.contract.company_id:
                    self.object.company_id = self.object.contract.company_id
                elif getattr(self.request, 'active_company', None):
                    self.object.company = self.request.active_company

            # Save the Clin instance directly
            self.object.save()
            
            # Create related ClinAcknowledgment
            ClinAcknowledgment.objects.create(
                clin=self.object,
                created_by=self.request.user,
                modified_by=self.request.user
            )
            
            messages.success(self.request, 'CLIN created successfully.')
            return HttpResponseRedirect(self.get_success_url())
            
        except Nsn.DoesNotExist:
            form.add_error('nsn', 'Selected NSN does not exist')
            return self.form_invalid(form)
        except Supplier.DoesNotExist:
            form.add_error('supplier', 'Selected Supplier does not exist')
            return self.form_invalid(form)
        except Contract.DoesNotExist:
            form.add_error('contract', 'Selected Contract does not exist')
            return self.form_invalid(form)
        except Exception as e:
            print(f"Error saving CLIN: {str(e)}")
            form.add_error(None, f"Error saving CLIN: {str(e)}")
            return self.form_invalid(form)
    
    def form_invalid(self, form):
        # Log form errors for debugging
        print("Form invalid with errors:", form.errors)
        messages.error(self.request, 'Unable to save CLIN. Please correct the errors below.')
        return super().form_invalid(form)
    
    def get_success_url(self):
        if self.object.contract_id:
            return reverse('contracts:contract_management', kwargs={'pk': self.object.contract_id})
        return reverse('contracts:contracts_dashboard')


@method_decorator(conditional_login_required, name='dispatch')
class ClinAcknowledgmentUpdateView(UpdateView):
    model = ClinAcknowledgment
    form_class = ClinAcknowledgmentForm
    template_name = 'contracts/clin_acknowledgment_form.html'
    
    def form_valid(self, form):
        clin_acknowledgment = form.save(commit=False)
        
        # Update acknowledgment status
        if form.cleaned_data.get('acknowledged'):
            clin_acknowledgment.acknowledged_date = timezone.now()
            clin_acknowledgment.acknowledged_by = self.request.user
        
        # Update rejection status
        if form.cleaned_data.get('rejected'):
            clin_acknowledgment.rejected_date = timezone.now()
            clin_acknowledgment.rejected_by = self.request.user
        
        clin_acknowledgment.save()
        messages.success(self.request, 'CLIN acknowledgment updated successfully.')
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('contracts:clin_detail', kwargs={'pk': self.object.clin.pk})


@conditional_login_required
def get_clin_notes(request, clin_id):
    try:
        active_company = getattr(request, 'active_company', None)
        if not active_company:
            return JsonResponse({'success': False, 'error': 'No company selected. Please select a company from the header.'}, status=400)
        clin = get_object_or_404(Clin, id=clin_id, company=active_company)
        
        # Get notes for this CLIN
        clin_type = ContentType.objects.get_for_model(Clin)
        
        notes = list(
            Note.objects.filter(
                content_type=clin_type,
                object_id=clin.id,
            ).select_related('created_by', 'assigned_to').order_by('-created_on')
        )

        for note in notes:
            setattr(note, 'entity_type', 'clin')
            setattr(note, 'content_type_id', clin_type.id)
            setattr(note, 'object_id', clin.id)
        annotate_notes_for_current_user(notes, request)
        
        # Format notes for JSON response
        notes_data = []
        for note in notes:
            notes_data.append({
                'id': note.id,
                'note': note.note,
                'created_by': note.created_by.username if note.created_by else 'Unknown',
                'created_on': note.created_on.strftime('%b %d, %Y %H:%M'),
                'has_reminder': bool(getattr(note, 'current_user_has_reminder', False)),
            })
        
        # Also render HTML for direct insertion
        notes_html = render_to_string(
            'contracts/partials/notes_list.html',
            {
                'notes': notes,
                'content_object': clin,
                'entity_type': 'clin',
                'content_type_id': str(clin_type.id),
                'object_id': clin.id,
                'note_empty_msg': 'No CLIN notes',
            },
            request=request,
        )
        
        return JsonResponse({
            'success': True,
            'notes': notes_data,
            'notes_html': notes_html
        })
    except Http404:
        return JsonResponse({'success': False, 'error': 'CLIN not found.'}, status=404)
    except Exception as e:
        import traceback
        print(f"Error in get_clin_notes: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@conditional_login_required
@require_http_methods(["POST"])
def toggle_clin_acknowledgment(request, clin_id):
    try:
        clin = get_object_or_404(
            Clin.objects.select_related('contract'),
            id=clin_id,
            company=request.active_company,
        )
        data = json.loads(request.body)
        field = data.get('field')
        initial_state = data.get('initial_state', False)
        
        if not field:
            return JsonResponse({'error': 'Field parameter is required'}, status=400)
        
        acknowledgment = clin.clinacknowledgment_set.first()
        if not acknowledgment:
            acknowledgment = ClinAcknowledgment.objects.create(clin=clin)
        
        current_value = getattr(acknowledgment, field, False)
        new_value = not current_value
        
        # Special case - if it's already true, don't toggle
        if (field == 'po_to_supplier_bool' or field == 'clin_reply_bool' or field == 'po_to_qar_bool') and current_value:
            return JsonResponse({
                'success': True,
                'status': current_value,
                'message': f'{field} is already set to true'
            })
        
        # Update the field and corresponding timestamp/user
        setattr(acknowledgment, field, new_value)
        
        # Initialize response data
        response_data = {
            'success': True,
            'status': new_value,
            'note_created': False,
            'reminder_created': False
        }
        
        # Update the corresponding user and date fields
        field_base = field.replace('_bool', '')
        date_field = f"{field_base}_date"
        user_field = f"{field_base}_user"
        
        if new_value:
            current_time = timezone.now()
            setattr(acknowledgment, date_field, current_time)
            setattr(acknowledgment, user_field, request.user)
            
            # Add user info to response
            response_data['user_info'] = {
                'username': request.user.username,
                'date': current_time.strftime('%m/%d/%Y %H:%M %p')
            }
            
            # Special processing for po_to_supplier_bool when toggled from false to true
            if field == 'po_to_supplier_bool' and not initial_state:
                # Create a note for the CLIN
                clin_content_type = ContentType.objects.get_for_model(Clin)
                note_text = f"PO ACKNOWLEDGMENT LETTER Followup - {request.user.username} on {current_time.strftime('%m/%d/%Y %H:%M %p')}"
                
                note = Note.objects.create(
                    content_type=clin_content_type,
                    object_id=clin.id,
                    note=note_text,
                    created_by=request.user
                )
                
                response_data['note_created'] = True
                
                reminder_date = None
                reminder_title = "FIRST CHECK IN"

                if clin.supplier_due_date:
                    reminder_date = clin.supplier_due_date - timedelta(days=60)
                elif clin.due_date:
                    reminder_date = clin.due_date - timedelta(days=90)

                if not reminder_date:
                    response_data['reminder_warning'] = (
                        "No CLIN Due Date or Target Ship Date is set — check-in reminder was not created. "
                        "Set a due date on this CLIN and re-send PO to generate a reminder."
                    )
                else:
                    try:
                        reminder_datetime = datetime.combine(reminder_date, time(9, 0))
                        aware_reminder_datetime = timezone.make_aware(reminder_datetime)

                        Reminder.objects.create(
                            reminder_title=reminder_title,
                            reminder_text=(
                                f"Follow up on {clin.contract.contract_number} "
                                f"CLIN {clin.item_number} PO acknowledgment"
                            ),
                            reminder_date=aware_reminder_datetime,
                            reminder_user=request.user,
                            reminder_completed=False,
                            note=note,
                        )

                        response_data['reminder_created'] = True
                        response_data['reminder_title'] = reminder_title
                        response_data['reminder_date'] = aware_reminder_datetime.strftime('%m/%d/%Y')
                    except Exception as e:
                        logger.warning(
                            "Failed to create check-in reminder for CLIN %s: %s",
                            clin.id,
                            e,
                        )
                        response_data['reminder_error'] = str(e)
        else:
            # If toggling to false, clear the user and date fields
            setattr(acknowledgment, date_field, None)
            setattr(acknowledgment, user_field, None)
        
        acknowledgment.save()
        
        return JsonResponse(response_data)
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@conditional_login_required
@require_http_methods(["POST"])
def toggle_contract_acknowledgment(request, contract_id):
    try:
        contract = get_object_or_404(
            Contract,
            id=contract_id,
            company=request.active_company,
        )
        data = json.loads(request.body)
        field = data.get('field')
        if not field:
            return JsonResponse({'error': 'Field parameter is required'}, status=400)

        clins = list(
            Clin.objects.filter(contract=contract)
            .select_related('contract')
            .order_by('item_number')
        )

        first_p_clin = next((c for c in clins if c.item_type == 'P'), None)
        if not first_p_clin:
            return JsonResponse({
                'success': False,
                'error': 'No Production CLIN found on this contract.',
            })

        acknowledgment = first_p_clin.clinacknowledgment_set.first()
        if not acknowledgment:
            acknowledgment = ClinAcknowledgment.objects.create(clin=first_p_clin)

        current_value = getattr(acknowledgment, field, False)
        if field in ('po_to_supplier_bool', 'clin_reply_bool', 'po_to_qar_bool') and current_value:
            return JsonResponse({
                'success': True,
                'status': True,
                'message': f'{field} is already set',
            })

        new_value = not current_value
        setattr(acknowledgment, field, new_value)

        current_time = timezone.now()
        today = current_time.date()
        response_data = {
            'success': True,
            'status': new_value,
        }

        field_base = field.replace('_bool', '')
        date_field = f"{field_base}_date"
        user_field = f"{field_base}_user"

        if new_value:
            setattr(acknowledgment, date_field, current_time)
            setattr(acknowledgment, user_field, request.user)
            response_data['user_info'] = {
                'username': request.user.username,
                'date': current_time.strftime('%m/%d/%Y %H:%M %p'),
            }

            if field == 'po_to_supplier_bool':
                clin_content_type = ContentType.objects.get_for_model(Clin)
                notes_created = 0
                reminders_created = 0
                checkin_reminder_errors = []

                def make_note(clin, note_text):
                    return Note.objects.create(
                        content_type=clin_content_type,
                        object_id=clin.id,
                        note=note_text,
                        created_by=request.user,
                        company=request.active_company,
                    )

                def make_reminder(title, text, reminder_date, note):
                    dt = datetime.combine(reminder_date, time(9, 0))
                    aware_dt = timezone.make_aware(dt)
                    return Reminder.objects.create(
                        reminder_title=title,
                        reminder_text=text,
                        reminder_date=aware_dt,
                        reminder_user=request.user,
                        reminder_completed=False,
                        company=request.active_company,
                        note=note,
                    )

                try:
                    note_text = (
                        f"PO ACKNOWLEDGMENT LETTER Followup - {request.user.username} "
                        f"on {current_time.strftime('%m/%d/%Y %H:%M %p')}"
                    )
                    note = make_note(first_p_clin, note_text)
                    notes_created += 1
                    po_ack_reminder_date = today + timedelta(days=10)
                    make_reminder(
                        "PO ACKNOWLEDGEMENT",
                        (
                            f"Send PO Acknowledgement Letter for {contract.contract_number} "
                            f"CLIN {first_p_clin.item_number}"
                        ),
                        po_ack_reminder_date,
                        note,
                    )
                    reminders_created += 1
                except Exception as e:
                    logger.warning(
                        "Failed to create PO ack reminder for contract %s: %s",
                        contract.id,
                        e,
                    )
                    response_data['po_ack_reminder_error'] = str(e)

                production_clins = [c for c in clins if c.item_type == 'P']
                non_production_clins = [c for c in clins if c.item_type != 'P']

                by_supplier_due_date = defaultdict(list)
                for clin in production_clins:
                    by_supplier_due_date[clin.supplier_due_date].append(clin)

                checkin_clins = []
                for group in by_supplier_due_date.values():
                    checkin_clins.append(
                        min(group, key=lambda c: (c.item_number or '', c.pk))
                    )
                checkin_clins.extend(non_production_clins)

                for clin in checkin_clins:
                    try:
                        if clin.supplier_due_date:
                            note_text = (
                                f"FIRST SUPPLIER CHECK IN - {clin.contract.contract_number} "
                                f"CLIN {clin.item_number} - {request.user.username} "
                                f"on {current_time.strftime('%m/%d/%Y %H:%M %p')}"
                            )
                            note = make_note(clin, note_text)
                            notes_created += 1
                            checkin_reminder_date = clin.supplier_due_date - timedelta(days=60)
                            make_reminder(
                                "FIRST SUPPLIER CHECK IN",
                                (
                                    f"First check-in for {contract.contract_number} "
                                    f"CLIN {clin.item_number} — supplier due "
                                    f"{clin.supplier_due_date.strftime('%m/%d/%Y')}"
                                ),
                                checkin_reminder_date,
                                note,
                            )
                            reminders_created += 1
                        else:
                            note_text = (
                                "FIRST SUPPLIER CHECK IN — No supplier_due_date set, "
                                "reminder not created - "
                                f"{clin.contract.contract_number} CLIN {clin.item_number} - "
                                f"{request.user.username} "
                                f"on {current_time.strftime('%m/%d/%Y %H:%M %p')}"
                            )
                            make_note(clin, note_text)
                            notes_created += 1
                    except Exception as e:
                        logger.warning(
                            "Failed to create check-in reminder for CLIN %s: %s",
                            clin.id,
                            e,
                        )
                        checkin_reminder_errors.append(str(e))

                response_data['notes_created'] = notes_created
                response_data['reminders_created'] = reminders_created
                response_data['checkin_reminder_errors'] = checkin_reminder_errors
        else:
            setattr(acknowledgment, date_field, None)
            setattr(acknowledgment, user_field, None)

        acknowledgment.save()
        return JsonResponse(response_data)

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


def _get_clin_delete_context(clin):
    clin_ct = ContentType.objects.get_for_model(Clin)
    notes = Note.objects.filter(
        content_type=clin_ct,
        object_id=clin.pk,
    ).select_related("created_by")
    reminders = Reminder.objects.filter(note__in=notes).select_related("reminder_user")

    users_by_pk = {}
    for note in notes:
        if note.created_by:
            users_by_pk[note.created_by.pk] = note.created_by
    for reminder in reminders:
        if reminder.reminder_user:
            users_by_pk[reminder.reminder_user.pk] = reminder.reminder_user

    return {
        "splits_count": clin.splits.count(),
        "shipments_count": clin.shipments.count(),
        "finance_lines_count": clin.finance_lines.count(),
        "notes_count": notes.count(),
        "reminders_count": reminders.count(),
        "affected_users": sorted(users_by_pk.values(), key=lambda user: user.username),
    }


@conditional_login_required
def clin_delete(request, pk):
    clin = get_object_or_404(Clin, pk=pk, company=request.active_company)
    delete_context = _get_clin_delete_context(clin)

    if request.method == 'POST':
        if not request.user.is_staff:
            return HttpResponseForbidden("You do not have permission to delete this CLIN.")

        contract_id = clin.contract_id
        clin_label = clin.item_number or clin.clin_po_num or str(clin.pk)

        # Notes and reminders linked through ContentType do not cascade from Clin.
        clin_ct = ContentType.objects.get_for_model(Clin)
        notes = Note.objects.filter(content_type=clin_ct, object_id=clin.pk)
        Reminder.objects.filter(note__in=notes).delete()
        notes.delete()

        clin.delete()
        messages.success(request, f"CLIN {clin_label} has been permanently deleted.")
        return redirect("contracts:contract_management", pk=contract_id)

    if not request.user.is_staff:
        messages.error(request, "Only staff users can delete CLINs.")
        return redirect("contracts:clin_detail", pk=pk)

    context = dict(delete_context)
    context["clin"] = clin
    context["contract"] = clin.contract
    return render(request, "contracts/clin_delete_confirm.html", context)
