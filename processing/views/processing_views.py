from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import DetailView, UpdateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.forms import inlineformset_factory
from processing.models import (
    ProcessContract,
    ProcessClin,
    ProcessClinSplit,
    QueueContract,
    QueueClin,
    SequenceNumber,
)
from processing.services.pdf_parser import parse_award_pdf, ingest_parsed_award
from processing.services.contract_utils import detect_contract_type
from processing.forms import (
    ProcessContractForm,
    ProcessClinForm,
    ProcessClinFormSet,
    persist_clin_splits_for_contract,
)
from contracts.models import (
    Contract,
    Clin,
    ClinSplit,
    Buyer,
    IdiqContract,
    IdiqContractDetails,
    ClinType,
    SpecialPaymentTerms,
    ContractType,
    SalesClass,
    PaymentHistory,
    ContractStatus,
)
from products.models import Nsn
from suppliers.models import Supplier
import csv
import os
from io import StringIO
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy, reverse
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_POST, require_http_methods
from django.http import Http404
import json
from urllib.parse import quote
import logging
from decimal import Decimal, InvalidOperation
import random
from datetime import datetime, timedelta
from django.db.models import Count, Sum
from django.utils.decorators import method_decorator
from django.contrib.contenttypes.models import ContentType
from django.db import models

logger = logging.getLogger(__name__)


def get_default_contract_status():
    """
    Retrieve or create the default 'Open' contract status.
    Ensures finalised contracts don't fail because the status table is empty.
    """
    status, _ = ContractStatus.objects.get_or_create(description='Open')
    return status


def _get_default_sales_class():
    """
    Return the SalesClass row representing STATZ, or None if not seeded.

    Silent on missing — callers should treat None as "leave field blank".
    Logs a warning so the missing-seed condition is visible in logs.
    """
    sc = SalesClass.objects.filter(sales_team='STATZ').first()
    if sc is None:
        logger.warning(
            "Default SalesClass 'STATZ' not found; ProcessContract.sales_class will be left blank."
        )
    return sc


@login_required
@require_POST
def start_new_contract(request):
    """Start a new contract

    This function is called when the user clicks the "Start New Contract" button in the contract queue.
    It creates a new contract in the database and returns the contract ID.

    The contract number is passed in the request body.
    The function then creates a new contract in the database and returns the contract ID.
    """
    try:
        #Get the contract number from the request body
        data = json.loads(request.body.decode('utf-8'))
        contract_number = data.get('contract_number')

        if not contract_number:
            return JsonResponse({
                'success': False,
                'error': 'No contract number provided'
            }, status=400)

        #Check if the contract number already exists in the ProcessContract table
        if ProcessContract.objects.filter(contract_number=contract_number).exists():
            return JsonResponse({
                'success': False,
                'error': 'Contract number already exists'
            }, status=400)
        
        #Check if the contract number already exists in the QueueContract table
        if QueueContract.objects.filter(contract_number=contract_number).exists():
            return JsonResponse({
                'success': False,
                'error': 'Contract number already exists'
            }, status=400)
        
        #Check if the contract number already exists in the Contract table
        if Contract.objects.filter(contract_number=contract_number).exists():
            return JsonResponse({
                'success': False,
                'error': 'Contract number already exists'
            }, status=400)

        #Get next po_number and tab_num from the sequence table
        new_po_number = SequenceNumber.get_po_number()
        new_tab_number = SequenceNumber.get_tab_number()
        #print(f"Pulled new PO and Tab numbers: {new_po_number} and {new_tab_number}")


        #step 1: create a new queue contract in the database
        queue_contract = QueueContract.objects.create(
            contract_number=contract_number,
            award_date=timezone.now(),
            created_by=request.user,
            modified_by=request.user
        )

        queue_item = get_object_or_404(QueueContract, id=queue_contract.id)
        queue_item.is_being_processed = True
        queue_item.processed_by = request.user
        queue_item.processing_started = timezone.now()
        queue_item.save()


        #Create a new blank contract in the database
        process_contract = ProcessContract.objects.create(
            queue_id=queue_contract.id,
            contract_number=contract_number,
            po_number=new_po_number,
            tab_num=new_tab_number,
            status='in_progress',
            files_url='\\STATZFS01\public\CJ_Data\data\V87\aFed-DOD\Contract ' + contract_number,
            sales_class=_get_default_sales_class(),
            created_by=request.user,
            modified_by=request.user
        )
        #print(f"Created new contract: {process_contract}")

        # Create ProcessClins from queue item
        ProcessClin.objects.create(
            process_contract=process_contract,

            item_number='0001',
            item_type='P',  # Changed back to 'P' as it's likely an enum/choice field
            tab_num=new_tab_number,
            clin_po_num=new_po_number,
            status='in_progress',
            created_at=timezone.now(),
            modified_at=timezone.now()
        )
        #print(f"Created new CLIN: {process_contract.clins.first()}")

        return JsonResponse({
            'success': True,
            'process_contract_id': process_contract.id,
            'message': 'Contract created successfully'
        })
    except Exception as e:
        if 'process_contract' in locals():
            process_contract.delete()
        #print(f"Error in start_new_contract: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_POST
def start_processing(request, queue_id):
    """Start the detailed processing workflow for a contract from the queue.
    
    This function is called after initiate_processing (in queue_views.py) has marked the contract
    as being processed. This function creates the actual processing records:
    1. Creates a ProcessContract from the queue item
    2. Creates ProcessClins from the queue item's CLINs
    3. Updates the queue item status
    
    This represents the start of the actual processing workflow, where data will be
    validated and matched against the database.
    """
    try:
        queue_item = get_object_or_404(QueueContract, id=queue_id)
        
        if queue_item.is_being_processed:
            return JsonResponse({
                'success': False,
                'error': 'This contract is already being processed by another user'
            })
        
        new_po_number = SequenceNumber.get_po_number()
        new_tab_number = SequenceNumber.get_tab_number()
        SequenceNumber.advance_po_number()
        SequenceNumber.advance_tab_number()

        # Create ProcessContract from queue item
        process_contract = ProcessContract.objects.create(
            contract_number=queue_item.contract_number,
            buyer_text=queue_item.buyer,
            solicitation_type=queue_item.solicitation_type,
            contract_type_text=queue_item.matched_contract_type,
            award_date=queue_item.award_date,
            due_date=queue_item.due_date,
            contract_value=queue_item.contract_value,
            po_number=new_po_number,
            tab_num=new_tab_number,
            status='in_progress',
            queue_id=queue_id,
            description=queue_item.description,
            files_url='\\STATZFS01\public\CJ_Data\data\V87\aFed-DOD\Contract ' + queue_item.contract_number,
            sales_class=_get_default_sales_class(),
            created_by=request.user,
            modified_by=request.user
        )
        
        # Create ProcessClins from queue item
        for clin_data in queue_item.clins.all():
            try:
                ProcessClin.objects.create(
                    process_contract=process_contract,
                    item_number=clin_data.item_number,
                    item_type=clin_data.item_type,
                    nsn_text=clin_data.nsn,
                    nsn_description_text=clin_data.nsn_description,
                    supplier_text=clin_data.supplier,
                    order_qty=float(clin_data.order_qty) if clin_data.order_qty else 0,
                    unit_price=clin_data.unit_price if clin_data.unit_price else 0,
                    item_value=clin_data.item_value if clin_data.item_value else 0,
                    status='in_progress',
                    ia=clin_data.ia if hasattr(clin_data, 'ia') else None,
                    fob=clin_data.fob if hasattr(clin_data, 'fob') else None,
                    due_date=clin_data.due_date if hasattr(clin_data, 'due_date') else None,
                    po_num_ext=clin_data.po_num_ext if hasattr(clin_data, 'po_num_ext') else None,
                    tab_num=new_tab_number,
                    clin_po_num=new_po_number,
                    po_number=new_po_number,
                    uom=clin_data.uom if clin_data.uom else None,
                    clin_type_text=clin_data.clin_type if hasattr(clin_data, 'clin_type') else None,
                    supplier_due_date=clin_data.supplier_due_date if hasattr(clin_data, 'supplier_due_date') else None,
                    price_per_unit=clin_data.supplier_unit_price if hasattr(clin_data, 'supplier_unit_price') else None,
                    quote_value=clin_data.supplier_price if hasattr(clin_data, ' supplier_price') else None,
                    special_payment_terms_text=clin_data.special_payment_terms if hasattr(clin_data, 'special_payment_terms') else None
                )
            except Exception as clin_error:
                # If CLIN creation fails, delete the process contract and raise error
                process_contract.delete()
                raise Exception(f"Error creating CLIN: {str(clin_error)}")
        
        # Update queue item status and timestamp
        queue_item.is_being_processed = True
        queue_item.processed_by = request.user
        queue_item.processing_started = timezone.now()
        queue_item.save()

        # Route IDIQ contracts to their dedicated processing page
        if queue_item.contract_type == 'IDIQ':
            redirect_url = reverse('processing:idiq_processing_edit', args=[process_contract.id])
            return JsonResponse({
                'success': True,
                'process_contract_id': process_contract.id,
                'redirect_url': redirect_url,
                'message': 'IDIQ contract processing started successfully'
            })

        return JsonResponse({
            'success': True,
            'process_contract_id': process_contract.id,
            'message': 'Contract processing started successfully'
        })
    except QueueContract.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Contract not found'
        })
    except Exception as e:
        # Log the full error for debugging
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in start_processing: {error_details}")
        
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


class ProcessContractDetailView(LoginRequiredMixin, DetailView):
    model = ProcessContract
    template_name = 'processing/process_contract_detail.html'
    context_object_name = 'process_contract'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['clins'] = self.object.clins.all().order_by('item_number')
        return context

class ProcessContractUpdateView(LoginRequiredMixin, UpdateView):
    model = ProcessContract
    form_class = ProcessContractForm
    template_name = 'processing/process_contract_form.html'
    context_object_name = 'process_contract'
    
    def get_object(self, queryset=None):
        try:
            obj = super().get_object(queryset)
            if obj is None:
                raise Http404("Process contract not found")
            return obj
        except Http404:
            messages.error(self.request, 'Process contract not found.')
            return None
    
    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object is None:
            return redirect('processing:queue')
        return super().get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object is None:
            return redirect('processing:queue')
        return super().post(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        process_contract = self.object
        clin_qs = (
            ProcessClin.objects.filter(process_contract=process_contract)
            .prefetch_related('splits')
            .order_by('item_number')
        )
        if self.request.POST:
            context['clin_formset'] = ProcessClinFormSet(
                self.request.POST,
                instance=process_contract,
                queryset=clin_qs,
            )
        else:
            context['clin_formset'] = ProcessClinFormSet(
                instance=process_contract,
                queryset=clin_qs,
            )
        context['process_clin_split_rollup'] = (
            ProcessClinSplit.objects.filter(clin__process_contract=process_contract)
            .values('company_name')
            .annotate(
                total_value=Sum('split_value'),
                total_paid=Sum('split_paid'),
            )
            .order_by('company_name')
        )
        # Add all IDIQ contracts to the context
        context['idiq_contracts'] = IdiqContract.objects.filter(closed=False).order_by('contract_number')

        # Add all CLIN types to the context
        context['clin_types'] = ClinType.objects.all().order_by('description')

        # Add all Contract types to the context
        context['contract_types'] = ContractType.objects.all().order_by('description')

        # Add all special payment terms to the context
        context['special_payment_terms'] = SpecialPaymentTerms.objects.all().order_by('terms')

        # Add all sales classes to the context
        context['sales_classes'] = SalesClass.objects.all().order_by('sales_team')

        queue_contract = None
        if self.object and self.object.queue_id:
            queue_contract = QueueContract.objects.filter(
                pk=self.object.queue_id
            ).first()
        context['queue_contract'] = queue_contract
        context['pdf_parse_status'] = (
            queue_contract.pdf_parse_status if queue_contract else None
        )
        context['pdf_parse_notes'] = (
            (queue_contract.pdf_parse_notes or "") if queue_contract else ""
        )
        
        return context
    
    def form_valid(self, form):
        context = self.get_context_data()
        clin_formset = context['clin_formset']
        
        if clin_formset.is_valid():
            self.object = form.save()
            clin_formset.instance = self.object
            clin_formset.save()
            messages.success(self.request, 'Contract updated successfully.')
            return redirect(self.get_success_url())
        else:
            return self.render_to_response(self.get_context_data(form=form))
    
    def get_success_url(self):
        return reverse('processing:process_contract_detail', kwargs={'pk': self.object.pk})

@login_required
def match_buyer(request, process_contract_id):
    """Match a buyer based on ID"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)
    
    try:
        # Log the raw request body for debugging
        print("Raw request body:", request.body)
        
        data = json.loads(request.body)
        print("Parsed JSON data:", data)
        
        buyer_id = data.get('id')
        print("Buyer ID:", buyer_id)
        
        if not buyer_id:
            return JsonResponse({'error': 'No buyer ID provided'}, status=400)
        
        process_contract = ProcessContract.objects.get(id=process_contract_id)
        print("Found ProcessContract:", process_contract)
        
        buyer = Buyer.objects.get(id=buyer_id)
        print("Found Buyer:", buyer)
        
        # Update all buyer fields using the correct field names
        process_contract.buyer = buyer
        process_contract.buyer_text = buyer.description  # Using description field from Buyer model
        process_contract.save()
        
        return JsonResponse({
            'success': True,
            'buyer_id': buyer.id,
            'buyer_name': buyer.description  # Using description field from Buyer model
        })
    except ProcessContract.DoesNotExist:
        print("ProcessContract not found:", process_contract_id)
        return JsonResponse({
            'error': 'Process contract not found'
        }, status=404)
    except Buyer.DoesNotExist:
        print("Buyer not found:", buyer_id)
        return JsonResponse({
            'error': 'Buyer not found'
        }, status=404)
    except json.JSONDecodeError as e:
        print("JSON decode error:", str(e))
        print("Raw body:", request.body)
        return JsonResponse({
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        import traceback
        print("Unexpected error:", str(e))
        print("Traceback:", traceback.format_exc())
        return JsonResponse({
            'error': str(e)
        }, status=500)

@login_required
def match_nsn(request, process_clin_id):
    """Match an NSN by ID, search NSNs (GET), or create a new NSN and link (POST)."""
    if request.method == 'GET':
        action = request.GET.get('action')
        if action == 'search':
            q = request.GET.get('q', '').strip()
            if len(q) < 3:
                return JsonResponse({'results': []})
            results = Nsn.objects.filter(
                models.Q(nsn_code__icontains=q) | models.Q(description__icontains=q)
            )[:20]
            return JsonResponse({
                'results': [
                    {'id': n.id, 'nsn_code': n.nsn_code, 'nsn': n.nsn_code, 'description': n.description or ''}
                    for n in results
                ]
            })
        return JsonResponse({'error': 'Invalid action'}, status=400)

    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    try:
        data = json.loads(request.body)
        action = data.get('action')

        if action == 'create':
            nsn_code = (data.get('nsn_code') or '').strip()
            description = (data.get('description') or '').strip()
            if not nsn_code:
                return JsonResponse({'success': False, 'error': 'NSN code required'}, status=400)
            nsn = Nsn.objects.create(
                nsn_code=nsn_code,
                description=description,
                created_by=request.user,
                modified_by=request.user,
            )
            process_clin = ProcessClin.objects.get(id=process_clin_id)
            process_clin.nsn = nsn
            process_clin.nsn_text = nsn.nsn_code
            process_clin.nsn_description_text = (nsn.description or '')[:255]
            process_clin.save()
            return JsonResponse({'success': True, 'nsn_id': nsn.id, 'nsn_code': nsn.nsn_code})

        nsn_id = data.get('id') or data.get('nsn_id')
        if not nsn_id:
            return JsonResponse({'error': 'No NSN ID provided'}, status=400)

        process_clin = ProcessClin.objects.get(id=process_clin_id)
        nsn = Nsn.objects.get(id=nsn_id)
        process_clin.nsn = nsn
        process_clin.nsn_text = nsn.nsn_code
        process_clin.nsn_description_text = (nsn.description or '')[:255]
        process_clin.save()

        return JsonResponse({
            'success': True,
            'nsn_id': nsn.id,
            'nsn_number': nsn.nsn_code,
            'nsn_description': nsn.description,
        })
    except ProcessClin.DoesNotExist:
        return JsonResponse({'error': 'Process CLIN not found'}, status=404)
    except Nsn.DoesNotExist:
        return JsonResponse({'error': 'NSN not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        import traceback
        print("Unexpected error:", str(e))
        print("Traceback:", traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def match_supplier(request, process_clin_id):
    """Match a supplier by ID, search suppliers (GET), or create and link (POST)."""
    if request.method == 'GET':
        action = request.GET.get('action')
        if action == 'search':
            q = request.GET.get('q', '').strip()
            if len(q) < 3:
                return JsonResponse({'results': []})
            results = Supplier.objects.filter(
                models.Q(name__icontains=q) | models.Q(cage_code__icontains=q)
            )[:20]
            return JsonResponse({
                'results': [
                    {
                        'id': s.id,
                        'name': s.name,
                        'cage': s.cage_code,
                        'cage_code': s.cage_code,
                    }
                    for s in results
                ]
            })
        return JsonResponse({'error': 'Invalid action'}, status=400)

    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    try:
        data = json.loads(request.body)
        action = data.get('action')

        if action == 'create':
            name = (data.get('name') or '').strip()
            cage_code = (data.get('cage_code') or data.get('cage') or '').strip()
            if not name:
                return JsonResponse({'success': False, 'error': 'Supplier name required'}, status=400)
            if not cage_code:
                return JsonResponse({'success': False, 'error': 'CAGE code required'}, status=400)
            supplier = Supplier.objects.create(
                name=name,
                cage_code=cage_code,
                created_by=request.user,
                modified_by=request.user,
            )
            process_clin = ProcessClin.objects.get(id=process_clin_id)
            process_clin.supplier = supplier
            process_clin.supplier_text = supplier.name
            process_clin.save()
            return JsonResponse({'success': True, 'supplier_id': supplier.id, 'supplier_name': supplier.name})

        supplier_id = data.get('supplier_id') or data.get('id')
        if not supplier_id:
            return JsonResponse({'error': 'No supplier ID provided'}, status=400)

        process_clin = ProcessClin.objects.get(id=process_clin_id)
        supplier = Supplier.objects.get(id=supplier_id)
        process_clin.supplier = supplier
        process_clin.supplier_text = supplier.name
        process_clin.save()

        return JsonResponse({
            'success': True,
            'supplier_id': supplier.id,
            'supplier_name': supplier.name,
        })
    except ProcessClin.DoesNotExist:
        return JsonResponse({'error': 'Process CLIN not found'}, status=404)
    except Supplier.DoesNotExist:
        return JsonResponse({'error': 'Supplier not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@transaction.atomic
def finalize_contract(request, process_contract_id):
    """Create a final Contract from a ProcessContract"""
    try:
        process_contract = ProcessContract.objects.get(id=process_contract_id)
        
        # Verify all required fields are set
        if not process_contract.buyer:
            return JsonResponse({
                'success': False,
                'error': 'Buyer must be matched before finalizing'
            })
        
        # Create the Contract
        contract = Contract.objects.create(
            contract_number=process_contract.contract_number,
            idiq_contract=process_contract.idiq_contract,
            solicitation_type=process_contract.solicitation_type,
            po_number=process_contract.po_number,
            tab_num=process_contract.tab_num,
            buyer=process_contract.buyer,
            contract_type=process_contract.contract_type,
            award_date=process_contract.award_date,
            due_date=process_contract.due_date,
            sales_class=process_contract.sales_class,
            nist=process_contract.nist,
            files_url=process_contract.files_url,
            contract_value=process_contract.contract_value,
            planned_split=process_contract.planned_split,
            created_by=request.user,
            modified_by=request.user,
            status=get_default_contract_status()
        )
        
        # Update sequence numbers if necessary
        po_number_current = SequenceNumber.get_po_number()
        tab_number_current = SequenceNumber.get_tab_number()

        # For PO number: Ensure sequence is at least one more than the contract's number
        target_po_number = process_contract.po_number + 1
        if po_number_current <= process_contract.po_number:
            # Need to advance sequence to be one more than contract's number
            sequence = SequenceNumber.objects.first()
            if sequence:
                sequence.po_number = target_po_number
                sequence.save()

        # For Tab number: Ensure sequence is at least one more than the contract's number
        target_tab_number = process_contract.tab_num + 1
        if tab_number_current <= process_contract.tab_num:
            # Need to advance sequence to be one more than contract's number
            sequence = SequenceNumber.objects.first()
            if sequence:
                sequence.tab_number = target_tab_number
                sequence.save()

        # Create CLINs
        for process_clin in process_contract.clins.prefetch_related('splits'):
            if not process_clin.nsn:
                return JsonResponse({
                    'success': False,
                    'error': f'NSN must be matched for CLIN {process_clin.item_number}'
                })
            if not process_clin.supplier:
                return JsonResponse({
                    'success': False,
                    'error': f'Supplier must be matched for CLIN {process_clin.item_number}'
                })
            
            clin = Clin.objects.create(
                contract=contract,
                item_number=process_clin.item_number,
                item_type=process_clin.item_type,
                nsn=process_clin.nsn,
                supplier=process_clin.supplier,
                order_qty=process_clin.order_qty,
                unit_price=process_clin.unit_price,
                item_value=process_clin.item_value,
                po_num_ext=process_clin.po_num_ext,
                tab_num=process_clin.tab_num,
                clin_po_num=process_clin.clin_po_num,
                po_number=process_clin.po_number,
                clin_type=process_clin.clin_type,
                ia=process_clin.ia,
                fob=process_clin.fob,
                due_date=process_clin.due_date,
                supplier_due_date=process_clin.supplier_due_date,
                price_per_unit=process_clin.price_per_unit,
                quote_value=process_clin.quote_value,
                special_payment_terms=process_clin.special_payment_terms,
                created_by=request.user,
                modified_by=request.user
            )
            process_clin.final_clin = clin
            process_clin.save(update_fields=['final_clin'])
            for proc_split in process_clin.splits.all():
                ClinSplit.objects.create(
                    clin=clin,
                    company_name=proc_split.company_name,
                    split_value=proc_split.split_value,
                    split_paid=(
                        proc_split.split_paid
                        if proc_split.split_paid is not None
                        else Decimal('0.00')
                    ),
                )
        
        # Update queue item status
        queue_contract = process_contract.queue_contract
        if queue_contract:
            queue_contract.status = 'processed'
            queue_contract.save()
        
        # Delete the process contract
        process_contract.delete()
        
        return JsonResponse({
            'success': True,
            'contract_id': contract.id,
            'message': 'Contract finalized successfully'
        })
    except ProcessContract.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Process contract not found'
        })
    except Exception as e:
        logger.exception("Error finalizing process contract %s", process_contract_id)
        return JsonResponse({
            'success': False,
            'error': f'Contract could not be finalized. {str(e)}'
        }, status=500)

@login_required
def match_idiq(request, process_contract_id):
    """Match an IDIQ contract based on ID"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)
    
    try:
        data = json.loads(request.body)
        idiq_id = data.get('idiq_id')
        
        process_contract = ProcessContract.objects.get(id=process_contract_id)
        
        if idiq_id is None:
            # Handle removal of IDIQ contract
            process_contract.idiq_contract = None
            process_contract.save()
            return JsonResponse({'success': True})
            
        # Handle setting new IDIQ contract
        idiq_contract = IdiqContract.objects.get(id=idiq_id)
        process_contract.idiq_contract = idiq_contract
        process_contract.save()
        
        return JsonResponse({
            'success': True,
            'idiq_id': idiq_contract.id,
            'contract_number': idiq_contract.contract_number
        })
    except ProcessContract.DoesNotExist:
        return JsonResponse({
            'error': 'Process Contract not found'
        }, status=404)
    except IdiqContract.DoesNotExist:
        return JsonResponse({
            'error': 'IDIQ Contract not found'
        }, status=404)
    except json.JSONDecodeError:
        return JsonResponse({
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        import traceback
        print("Unexpected error:", str(e))
        print("Traceback:", traceback.format_exc())
        return JsonResponse({
            'error': str(e)
        }, status=500)


@login_required
def get_process_contract(request, queue_id):
    """Get the process contract ID for a queue item to resume processing."""
    try:
        process_contract = ProcessContract.objects.get(queue_id=queue_id)
        queue_contract = QueueContract.objects.filter(id=queue_id).first()

        response_data = {
            'success': True,
            'process_contract_id': process_contract.id,
        }

        if queue_contract and queue_contract.contract_type == 'IDIQ':
            response_data['redirect_url'] = reverse(
                'processing:idiq_processing_edit',
                args=[process_contract.id]
            )

        return JsonResponse(response_data)
    except ProcessContract.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'No processing contract found'},
            status=404,
        )
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@require_POST
@transaction.atomic
def cancel_process_contract(request, process_contract_id=None, queue_id=None):
    """
    Cancel a process contract and return to queue.
    
    The primary use case is with process_contract_id, canceling from the process contract view.
    The queue_id parameter is maintained for API compatibility but doesn't currently have UI elements.
    """
    try:
        with transaction.atomic():
            # Case 1: Processing from process contract ID (primary use case)
            if process_contract_id:
                process_contract = get_object_or_404(ProcessContract, id=process_contract_id)
                
                # Only allow canceling if not already completed
                if process_contract.status == 'completed':
                    return JsonResponse({
                        'success': False,
                        'error': 'Cannot cancel a completed contract'
                    }, status=400)
                
                # Get the queue contract
                queue_contract = QueueContract.objects.get(id=process_contract.queue_id)
                
                # Reset queue contract status
                queue_contract.is_being_processed = False
                queue_contract.processed_by = None
                queue_contract.processing_started = None
                queue_contract.status = 'ready_for_processing'
                queue_contract.save()
                
                # Delete the process contract
                process_contract.delete()
                
            # Case 2: Processing from queue ID (not currently used in the UI)
            elif queue_id:
                queue_contract = get_object_or_404(QueueContract, id=queue_id)
                
                # Delete the ProcessContract if it exists
                ProcessContract.objects.filter(queue_id=queue_id).delete()
                
                # Reset the queue contract status
                queue_contract.is_being_processed = False
                queue_contract.processed_by = None
                queue_contract.processing_started = None
                queue_contract.save()
            
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Either process_contract_id or queue_id must be provided'
                }, status=400)
            
            return JsonResponse({
                'success': True,
                'message': 'Contract processing cancelled successfully'
            })
            
    except ProcessContract.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Process contract not found'
        }, status=404)
    except QueueContract.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Queue contract not found'
        }, status=404)
    except Exception as e:
        logger.exception("Error finalizing and emailing process contract %s", process_contract_id)
        return JsonResponse({
            'success': False,
            'error': f'Contract could not be finalized. {str(e)}'
        }, status=500)

# Keep this function as a wrapper for backward compatibility
@login_required
@require_POST
@transaction.atomic
def cancel_processing(request, process_contract_id=None, queue_id=None):
    """Cancel processing of a contract - wrapper for backward compatibility"""
    return cancel_process_contract(request, process_contract_id=process_contract_id, queue_id=queue_id)

@transaction.atomic
def save_and_return_to_queue(request, process_contract_id):
    """
    Save the current state of the process contract and return to queue
    """
    try:
        with transaction.atomic():
            process_contract = get_object_or_404(ProcessContract, id=process_contract_id)
            
            # Get the form data
            form = ProcessContractForm(request.POST, instance=process_contract)
            clin_formset = ProcessClinFormSet(request.POST, instance=process_contract)
            
            # Log form and formset data for debugging
            logger.debug(f"Form is_valid: {form.is_valid()}")
            logger.debug(f"CLIN formset is_valid: {clin_formset.is_valid()}")
            
            if not form.is_valid():
                logger.debug(f"Form errors: {form.errors}")
            
            if not clin_formset.is_valid():
                logger.debug(f"CLIN formset errors: {clin_formset.errors}")
                for i, form_errors in enumerate(clin_formset.errors):
                    if form_errors:
                        logger.debug(f"CLIN {i} errors: {form_errors}")
            
            if form.is_valid() and clin_formset.is_valid():
                # Save the contract
                process_contract = form.save()
                
                # Save the CLINs
                clin_formset.save()
                
                messages.success(request, 'Changes saved successfully')
                return JsonResponse({
                    'success': True,
                    'redirect_url': reverse('processing:queue')
                })
            else:
                # Collect detailed error information
                errors = {}
                
                # Add form errors if any
                if not form.is_valid():
                    errors['form_errors'] = {}
                    for field, error_list in form.errors.items():
                        errors['form_errors'][field] = error_list[0] if error_list else "Invalid value"
                
                # Add CLIN errors if any
                if not clin_formset.is_valid():
                    errors['clin_errors'] = []
                    for i, form_errors in enumerate(clin_formset.errors):
                        if form_errors:
                            # Get the CLIN number if possible
                            clin_prefix = f'clins-{i}-'
                            clin_number = request.POST.get(f'{clin_prefix}item_number', f'CLIN {i+1}')
                            
                            error_dict = {'item_number': clin_number}
                            for field, error_list in form_errors.items():
                                error_dict[field] = error_list[0] if error_list else "Invalid value"
                            
                            errors['clin_errors'].append(error_dict)
                
                return JsonResponse({
                    'success': False,
                    'errors': errors,
                    'error': 'Failed to save due to validation errors. Please check form values.'
                }, status=400)
            
    except ProcessContract.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Process contract not found'
        }, status=404)
    except Exception as e:
        logger.exception("Error in save_and_return_to_queue")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def process_contract_form(request, pk=None):
    """
    View for handling the processing contract form.
    Supports both creation and editing of ProcessContract instances.
    """
    if pk:
        instance = get_object_or_404(ProcessContract, pk=pk)
    else:
        instance = None
        
    if request.method == 'POST':
        form = ProcessContractForm(request.POST, request.FILES, instance=instance)
        
        if form.is_valid():
            try:
                instance = form.save()
                return JsonResponse({'status': 'success', 'message': 'Form saved successfully'})
            except Exception as e:
                return JsonResponse({
                    'status': 'error', 
                    'message': f'Error saving form: {str(e)}'
                }, status=500)
        else:
            return JsonResponse({
                'status': 'error', 
                'message': 'Invalid form data', 
                'errors': form.errors
            }, status=400)
    else:
        form = ProcessContractForm(instance=instance)
        
    context = {
        'form': form,
        'process_contract': instance,  # Add the process_contract instance to context
        'contract_types': ContractType.objects.all().order_by('description'),
        'sales_classes': SalesClass.objects.all().order_by('sales_team'),
        'special_payment_terms': SpecialPaymentTerms.objects.all().order_by('terms'),
    }
    return render(request, 'processing/process_contract_form.html', context)

@login_required
@require_http_methods(["POST"])
def create_split_view(request, clin_pk):
    try:
        data = json.loads(request.body)
        get_object_or_404(ProcessClin, pk=clin_pk)
        paid = data.get('split_paid')
        if paid is not None:
            paid = Decimal(str(paid))
        split = ProcessClinSplit.create_split(
            process_clin_id=clin_pk,
            company_name=data['company_name'],
            split_value=Decimal(str(data['split_value'])),
            split_paid=paid,
        )
        return JsonResponse({
            'success': True,
            'split_id': split.id,
            'company_name': split.company_name,
            'split_value': str(split.split_value) if split.split_value is not None else None,
            'split_paid': str(split.split_paid) if split.split_paid is not None else None,
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
@require_http_methods(["POST"])
def update_split_view(request, split_pk):
    try:
        data = json.loads(request.body)

        def ddec(key):
            if key not in data or data[key] is None or str(data[key]).strip() == '':
                return None
            return Decimal(str(data[key]).replace(',', ''))

        ProcessClinSplit.update_split(
            split_id=split_pk,
            company_name=data.get('company_name'),
            split_value=ddec('split_value'),
            split_paid=ddec('split_paid'),
        )
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
@require_http_methods(["POST"])
def delete_split_view(request, split_pk):
    try:
        success = ProcessClinSplit.delete_split(split_pk)
        return JsonResponse({'success': success})
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
@require_POST
def calc_splits_view(request, clin_pk):
    """Set or create STATZ process split as item_value - quote_value (floored at 0)."""
    process_clin = get_object_or_404(ProcessClin, pk=clin_pk)
    try:
        iv = process_clin.item_value
        qv = process_clin.quote_value
        a = iv if iv is not None else Decimal('0')
        b = qv if qv is not None else Decimal('0')
        statz = a - b
        if statz < 0:
            statz = Decimal('0')
        row = process_clin.splits.filter(company_name__iexact='STATZ').first()
        if row:
            row.split_value = statz
            row.split_paid = row.split_paid or Decimal('0')
            row.save()
        else:
            row = ProcessClinSplit.objects.create(
                clin=process_clin,
                company_name='STATZ',
                split_value=statz,
                split_paid=Decimal('0'),
            )
        return JsonResponse(
            {
                'success': True,
                'split_id': row.id,
                'company_name': 'STATZ',
                'split_value': str(row.split_value),
                'split_paid': '0',
            }
        )
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)

@login_required
@require_POST
@transaction.atomic
def mark_ready_for_review(request, process_contract_id):
    """
    Mark a process contract as ready for review and update queue status
    """
    try:
        with transaction.atomic():
            process_contract = get_object_or_404(ProcessContract, id=process_contract_id)
            
            # Get the queue contract
            queue_contract = QueueContract.objects.get(id=process_contract.queue_id)
            
            # Update queue contract status
            queue_contract.is_being_processed = True
            queue_contract.processed_by = request.user
            queue_contract.processing_started = timezone.now()
            queue_contract.save()
            
            # Update process contract status
            process_contract.status = 'ready_for_review'
            process_contract.modified_by = request.user
            process_contract.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Contract marked as ready for review'
            })
            
    except ProcessContract.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Process contract not found'
        }, status=404)
    except QueueContract.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Queue contract not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@require_http_methods(["POST"])
@transaction.atomic
def finalize_and_email_contract(request, process_contract_id):
    try:
        process_contract = get_object_or_404(ProcessContract, id=process_contract_id)
        process_clins = process_contract.clins.prefetch_related('splits')
        
        # Validate all CLINs before processing
        validation_errors = []
        for process_clin in process_clins:
            if not process_clin.nsn:
                validation_errors.append(f"CLIN {process_clin.item_number} is missing NSN")
            if not process_clin.supplier:
                validation_errors.append(f"CLIN {process_clin.item_number} is missing supplier")
            if not process_clin.item_value and process_clin.item_value != 0:
                validation_errors.append(f"CLIN {process_clin.item_number} has no item value")
            if not process_clin.quote_value and process_clin.quote_value != 0:
                validation_errors.append(f"CLIN {process_clin.item_number} has no quote value")
                
        if validation_errors:
            return JsonResponse({
                'success': False,
                'error': "Validation failed:\n" + "\n".join(validation_errors)
            }, status=400)

        # Validate contract level data
        if not process_contract.contract_value:
            return JsonResponse({
                'success': False,
                'error': "Contract has no total value"
            }, status=400)
            
        if not process_contract.plan_gross and process_contract.plan_gross != 0:
            return JsonResponse({
                'success': False,
                'error': "Contract has no plan gross value"
            }, status=400)
            
        if not process_contract.award_date:
            return JsonResponse({
                'success': False,
                'error': "Contract has no award date"
            }, status=400)


        # Update sequence numbers if necessary
        po_number_current = SequenceNumber.get_po_number()
        tab_number_current = SequenceNumber.get_tab_number()

        if po_number_current == int(process_contract.po_number):
            SequenceNumber.advance_po_number()

        # For Tab number: Ensure sequence is at least one more than the contract's number
        if tab_number_current == int(process_contract.tab_num):
            SequenceNumber.advance_tab_number()


        # Create the final contract with all relevant fields
        contract = Contract.objects.create(
            contract_number=process_contract.contract_number,
            idiq_contract=process_contract.idiq_contract,
            solicitation_type=process_contract.solicitation_type,
            po_number=process_contract.po_number,
            tab_num=process_contract.tab_num,
            buyer=process_contract.buyer,
            contract_type=process_contract.contract_type,
            award_date=process_contract.award_date,
            due_date=process_contract.due_date,
            sales_class=process_contract.sales_class,
            nist=process_contract.nist,
            files_url=process_contract.files_url,
            contract_value=process_contract.contract_value,
            planned_split=process_contract.planned_split,
            plan_gross=process_contract.plan_gross,
            created_by=request.user,
            modified_by=request.user,
            status=get_default_contract_status()
        )

        # Create contract_value payment history
        contract_content_type = ContentType.objects.get_for_model(Contract)
        PaymentHistory.objects.create(
            content_type=contract_content_type,
            object_id=contract.id,
            payment_type='contract_value',
            payment_amount=process_contract.contract_value,
            payment_date=process_contract.award_date.date(),
            payment_info='Initial contract value',
            created_by=request.user,
            modified_by=request.user
        )
        # Create plan_gross payment history
        PaymentHistory.objects.create(
            content_type=contract_content_type,
            object_id=contract.id,
            payment_type='plan_gross',
            payment_amount=process_contract.plan_gross,
            payment_date=process_contract.award_date.date(),
            payment_info='Initial plan gross',
            created_by=request.user,
            modified_by=request.user
        )

        # Create CLINs and payment history with all relevant fields
        for process_clin in process_clins:
            clin = Clin.objects.create(
                contract=contract,
                item_number=process_clin.item_number,
                item_type=process_clin.item_type,
                nsn=process_clin.nsn,
                supplier=process_clin.supplier,
                order_qty=process_clin.order_qty,
                unit_price=process_clin.unit_price,
                item_value=process_clin.item_value,
                po_num_ext=process_clin.po_num_ext,
                tab_num=process_clin.tab_num,
                clin_po_num=process_clin.clin_po_num,
                po_number=process_clin.po_number,
                clin_type=process_clin.clin_type,
                ia=process_clin.ia,
                fob=process_clin.fob,
                due_date=process_clin.due_date,
                supplier_due_date=process_clin.supplier_due_date,
                price_per_unit=process_clin.price_per_unit,
                quote_value=process_clin.quote_value,
                uom=process_clin.uom,
                special_payment_terms=process_clin.special_payment_terms,
                created_by=request.user,
                modified_by=request.user
            )

            process_clin.final_clin = clin
            process_clin.save(update_fields=['final_clin'])

            for proc_split in process_clin.splits.all():
                ClinSplit.objects.create(
                    clin=clin,
                    company_name=proc_split.company_name,
                    split_value=proc_split.split_value,
                    split_paid=(
                        proc_split.split_paid
                        if proc_split.split_paid is not None
                        else Decimal('0.00')
                    ),
                )
            
            # Create payment history records using ContentType framework
            clin_content_type = ContentType.objects.get_for_model(Clin)
            
            # Create item_value payment history
            PaymentHistory.objects.create(
                content_type=clin_content_type,
                object_id=clin.id,
                payment_type='item_value',
                payment_amount=process_clin.item_value,
                payment_date=process_contract.award_date.date(),
                payment_info='Initial item value',
                created_by=request.user,
                modified_by=request.user
            )
            
            # Create quote_value payment history
            PaymentHistory.objects.create(
                content_type=clin_content_type,
                object_id=clin.id,
                payment_type='quote_value',
                payment_amount=process_clin.quote_value,
                payment_date=process_contract.award_date.date(),
                payment_info='Initial quote value',
                created_by=request.user,
                modified_by=request.user
            )
            
        email_subject = f"New Contract: {contract.contract_number}"
        email_body = (
            f"A new Contract has been created\n\n"
            f"Tab #: {contract.tab_num}\n"
            f"PO #: {contract.po_number}\n"
            f"Contract #: {contract.contract_number}\n"
            f"{contract.files_url}"
        )

        from urllib.parse import quote

        # Create mailto URL
        mailto_url = (
            f"mailto:dmani@statzcorp.com?subject={quote(email_subject)}&"
            f"body={quote(email_body)}"
        )
        
        queue_contract = QueueContract.objects.get(id=process_contract.queue_id)

        # Delete the process contract
        process_contract.delete()

        # Delete the queue contract
        queue_contract.delete()
        
        return JsonResponse({
            'success': True,
            'mailto_url': mailto_url,
            'contract_id': contract.id,
            'message': 'Contract finalized successfully'
        })
        
    except ProcessContract.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Process contract not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error finalizing contract {process_contract_id}: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': f"Database error: {str(e)}"
        }, status=500)

@login_required
@require_POST
def save_contract(request):
    """Save a ProcessContract with data from FormData."""
    #print("\n========== SAVE CONTRACT DEBUG ==========")
    #print(f"All POST data: {request.POST}")

    from decimal import Decimal, InvalidOperation
    from datetime import datetime

    try:
        contract_id = request.POST.get('contract_id')
        if not contract_id:
            return JsonResponse({'success': False, 'error': 'Contract ID is required'}, status=400)

        contract = ProcessContract.objects.get(id=contract_id)
        changes_made = False
        updated_fields = {}

        # --- CONTRACT FIELDS ---
        contract_prefix = "cont_"
        # Map of field name to type for contract fields
        contract_field_types = {
            'contract_number': str,
            'solicitation_type': str,
            'po_number': str,
            'tab_num': str,
            'files_url': str,
            'planned_split': str,
            'description': str,
            'status': str,
            'buyer_text': str,
            'award_date': 'date',
            'due_date': 'date',
            'contract_value': Decimal,
            'plan_gross': Decimal,
            'nist': 'bool',
            'idiq_contract': 'fk',
            'contract_type': 'fk',
            'sales_class': 'fk',
            'buyer': 'fk'
        }
        
        fk_models = {
            'idiq_contract': IdiqContract,
            'contract_type': ContractType,
            'sales_class': SalesClass,
            'buyer': Buyer
        }

        #print("\nProcessing contract fields:")
        for key, value in request.POST.items():
            if key.startswith(contract_prefix):
                model_field = key[len(contract_prefix):]  # Remove cont_ prefix
                #print(f"Processing field: {model_field} = {value}")
                
                if not hasattr(contract, model_field):
                    #print(f"Skipping field {model_field} - not found in model")
                    continue
                
                field_type = contract_field_types.get(model_field, str)
                current = getattr(contract, model_field)
                new_value = value

                # Type conversion
                try:
                    if field_type == Decimal:
                        new_value = Decimal(str(value).replace(',', '')) if value else None
                    elif field_type == 'date':
                        new_value = datetime.strptime(value, '%Y-%m-%d').date() if value else None
                    elif field_type == 'bool':
                        new_value = value.lower() in ['true', 'yes', 'on', '1']
                    elif field_type == 'fk':
                        if value:
                            model = fk_models[model_field]
                            try:
                                new_value = model.objects.get(id=value)
                            except model.DoesNotExist:
                                print(f"Foreign key {model_field} with id {value} not found")
                                continue
                        else:
                            new_value = None
                except (InvalidOperation, ValueError) as e:
                    print(f"Error converting {model_field}: {str(e)}")
                    continue

                # Only update if changed
                if current != new_value:
                    #print(f"Updating {model_field}: {current} -> {new_value}")
                    setattr(contract, model_field, new_value)
                    updated_fields[model_field] = str(new_value) if new_value is not None else ''
                    changes_made = True

        splits_changed = persist_clin_splits_for_contract(contract, request.POST)

        if changes_made:
            contract.save()
            return JsonResponse({
                'success': True,
                'message': 'Contract saved successfully',
                'updated_fields': updated_fields
            })
        if splits_changed:
            return JsonResponse({
                'success': True,
                'message': 'Contract saved successfully',
            })
        return JsonResponse({
            'success': True,
            'message': 'No changes to save'
        })

    except Exception as e:
        import traceback
        #print(f"Error saving contract: {str(e)}")
        #print(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'error': f'Error saving contract: {str(e)}'
        }, status=500)
    #finally:
        #print("========== END SAVE CONTRACT DEBUG ==========")



@method_decorator(login_required, name='dispatch')
class ContractQueueListView(ListView):
    model = QueueContract
    template_name = 'processing/contract_queue.html'
    context_object_name = 'queued_contracts'
    
    def get_queryset(self):
        return QueueContract.objects.all().order_by('award_date')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add contract count info for debugging
        contract_count = QueueContract.objects.count()
        context['contract_count'] = contract_count
        
        if contract_count > 0:
            # Get counts by status
            processing_count = QueueContract.objects.filter(is_being_processed=True).count()
            context['processing_count'] = processing_count
            
            # Get CLIN counts
            total_clins = 0
            for contract in context['queued_contracts']:
                clin_count = contract.clins.count()
                contract.clin_count = clin_count
                total_clins += clin_count
            
            context['total_clins'] = total_clins
            
            # Add debug info for the first contract
            if contract_count > 0:
                first_contract = QueueContract.objects.first()
                context['first_contract_debug'] = {
                    'id': first_contract.id,
                    'contract_number': first_contract.contract_number,
                    'contract_type': first_contract.contract_type,
                    'clins': first_contract.clins.count(),
                    'created_on': first_contract.created_on
                }
        
        return context

@require_http_methods(["GET"])
@login_required
def get_next_numbers(request):
    """Get the next available PO and Tab numbers"""
    try:
        po_number = SequenceNumber.get_po_number()
        tab_number = SequenceNumber.get_tab_number()
        return JsonResponse({
            'success': True,
            'po_number': po_number,
            'tab_number': tab_number
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@require_http_methods(["POST"])
@login_required
def initiate_processing(request):
    """Initiate the processing of a contract by marking it as being processed.
    
    This is the first step in the contract processing workflow:
    1. Marks the contract as being processed (is_being_processed = True)
    2. Records which user is processing it (processed_by)
    3. Records when processing started (processing_started)
    
    After this function completes, the system will call start_processing (in processing_views.py)
    to begin the actual processing workflow.
    """
    contract_queue_id = request.POST.get('contract_queue_id')
    
    try:
        with transaction.atomic():
            contract_queue = QueueContract.objects.select_for_update().get(id=contract_queue_id)
            
            if contract_queue.is_being_processed:
                return JsonResponse({
                    'success': False,
                    'error': 'This contract is already being processed by another user'
                })
            
            contract_queue.is_being_processed = True
            contract_queue.processed_by = request.user
            contract_queue.processing_started = timezone.now()
            contract_queue.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Contract processing started'
            })
    except QueueContract.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Contract not found'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@require_http_methods(["POST"])
@login_required
def process_contract(request):
    """Process a queued contract and create a live contract"""
    contract_queue_id = request.POST.get('contract_queue_id')
    
    try:
        with transaction.atomic():
            contract_queue = QueueContract.objects.select_for_update().get(id=contract_queue_id)
            
            if not contract_queue.is_being_processed:
                return JsonResponse({
                    'success': False,
                    'error': 'Contract is not being processed'
                })
            
            if contract_queue.processed_by != request.user:
                return JsonResponse({
                    'success': False,
                    'error': 'You are not the user processing this contract'
                })
            
            # Create the live contract
            contract = Contract.objects.create(
                contract_number=contract_queue.contract_number,
                buyer=contract_queue.matched_buyer,
                award_date=contract_queue.award_date,
                due_date=contract_queue.due_date,
                contract_value=contract_queue.contract_value,
                contract_type=contract_queue.matched_contract_type,
                solicitation_type=contract_queue.solicitation_type,
                created_by=request.user,
                modified_by=request.user
            )
            
            # Process all CLINs
            for clin_queue in contract_queue.clins.all():
                Clin.objects.create(
                    contract=contract,
                    item_number=clin_queue.item_number,
                    item_type=clin_queue.item_type,
                    nsn=clin_queue.matched_nsn,
                    ia=clin_queue.ia,
                    fob=clin_queue.fob,
                    due_date=clin_queue.due_date,
                    order_qty=clin_queue.order_qty,
                    item_value=clin_queue.item_value,
                    unit_price=clin_queue.unit_price,
                    supplier=clin_queue.matched_supplier,
                    supplier_due_date=clin_queue.supplier_due_date,
                    created_by=request.user,
                    modified_by=request.user
                )
            
            # Delete the queued contract and its CLINs
            contract_queue.delete()
            
            return JsonResponse({
                'success': True,
                'message': 'Contract processed successfully',
                'contract_id': contract.id
            })
    except QueueContract.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Contract not found'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

def download_csv_template(request):
    """Download a CSV template for contract queue upload"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="contract_queue_template.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Contract Number',
        'Buyer',
        'Award Date',
        'Due Date',
        'Contract Value',
        'Contract Type',
        'Solicitation Type',
        'Item Number',
        'Item Type',
        'NSN',
        'NSN Description',
        'IA',
        'FOB',
        'Due Date',
        'Order Qty',
        'UOM',
        'Item Value',
        'Unit Price',
        'Supplier',
        'Supplier Due Date',
        'Supplier Unit Price',
        'Supplier Price',
        'Supplier Payment Terms'
    ])
    
    return response

def download_test_data(request):
    """Download sample test data for contract queue upload"""
    # Only allow in development environment
    if not settings.DEBUG:
        raise PermissionDenied("Test data download is only available in development environment")
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="contract_queue_test_data.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Contract Number',
        'Buyer',
        'Award Date',
        'Due Date',
        'Contract Value',
        'Contract Type',
        'Solicitation Type',
        'Item Number',
        'Item Type',
        'NSN',
        'NSN Description',
        'IA',
        'FOB',
        'Due Date',
        'Order Qty',
        'UOM',
        'Item Value',
        'Unit Price',
        'Supplier',
        'Supplier Due Date',
        'Supplier Unit Price',
        'Supplier Price',
        'Supplier Payment Terms'
    ])
    
    try:
        # Get total count of NSNs and Suppliers
        nsn_count = Nsn.objects.count()
        supplier_count = Supplier.objects.count()
        
        # Get random NSNs (15 or all if less than 15)
        nsn_limit = min(15, nsn_count)
        nsn_ids = random.sample(range(1, nsn_count + 1), nsn_limit) if nsn_count > 0 else []
        real_nsns = list(Nsn.objects.filter(id__in=nsn_ids).values_list('nsn_code', 'description'))
        
        # Get random Suppliers (15 or all if less than 15)
        supplier_limit = min(15, supplier_count)
        supplier_ids = random.sample(range(1, supplier_count + 1), supplier_limit) if supplier_count > 0 else []
        real_suppliers = list(Supplier.objects.filter(id__in=supplier_ids).values_list('name', flat=True))
        
        # Get buyers
        real_buyers = list(Buyer.objects.values_list('description', flat=True)[:10])
        
        # Generate 10 contracts
        for i in range(10):
            # Generate award date and use it for contract number
            award_date = datetime.now() - timedelta(days=random.randint(1, 30))
            year = award_date.strftime('%y')
            contract_number = f"STATZ-{year}-P-{random.randint(1000, 9999)}"
            
            # Mix of real and made-up buyers
            if i < len(real_buyers):
                buyer = real_buyers[i]
            else:
                buyer = f"Test Buyer {i+1}"
            
            due_date = (award_date + timedelta(days=random.randint(30, 90))).strftime('%Y-%m-%d')
            award_date_str = award_date.strftime('%Y-%m-%d')
            contract_type = random.choice(['Unilateral', 'Bilateral', 'IDIQ'])
            solicitation_type = 'SDVOSB'
            
            # Initialize contract value
            contract_value = 0
            
            # Generate 1-4 CLINs per contract
            num_clins = random.randint(1, 4)
            clin_data = []
            
            # First CLIN must be Production
            item_number = "0001"
            item_type = "Production"
            uom = "EA"
            
            # Generate CLIN data
            order_qty = random.randint(1, 100)
            unit_price = round(random.uniform(100, 1000), 2)
            item_value = round(order_qty * unit_price, 2)
            contract_value += item_value
            
            # Mix of real and made-up NSNs
            if real_nsns and random.random() > 0.3:  # 70% chance to use real NSN
                nsn, nsn_description = random.choice(real_nsns)
            else:
                nsn = f"TEST{i+1:03d}01"  # Format as TEST00101, TEST00102, etc.
                nsn_description = f"Test NSN Description {i+1}01"
            
            ia = random.choice(['O', 'D'])
            fob = random.choice(['O', 'D'])
            clin_due_date = (award_date + timedelta(days=random.randint(30, 90))).strftime('%Y-%m-%d')
            
            # Randomly decide if this CLIN should have supplier data (about 30% won't)
            has_supplier = random.random() > 0.3
            
            if has_supplier and real_suppliers and random.random() > 0.3:  # 70% chance to use real supplier
                supplier = random.choice(real_suppliers)
            elif has_supplier:
                supplier = f"Test Supplier {i+1:03d}01"  # Format as TEST00101, TEST00102, etc.
            else:
                supplier = ''
            
            if has_supplier and supplier:
                supplier_due_date = (award_date + timedelta(days=random.randint(15, 45))).strftime('%Y-%m-%d')
                supplier_unit_price = round(unit_price * random.uniform(0.8, 1.2), 2)
                supplier_price = round(supplier_unit_price * order_qty, 2)
                supplier_payment_terms = random.choice(['Net 30', 'Net 45', 'Net 60'])
            else:
                supplier_due_date = ''
                supplier_unit_price = ''
                supplier_price = ''
                supplier_payment_terms = ''
            
            # Add first CLIN data
            clin_data.append([
                contract_number,
                buyer,
                award_date_str,
                due_date,
                contract_value,  # Will be updated after all CLINs
                contract_type,
                solicitation_type,
                item_number,
                item_type,
                nsn,
                nsn_description,
                ia,
                fob,
                clin_due_date,
                order_qty,
                uom,
                item_value,
                unit_price,
                supplier,
                supplier_due_date,
                supplier_unit_price,
                supplier_price,
                supplier_payment_terms
            ])
            
            # Generate additional CLINs
            for j in range(1, num_clins):
                item_number = f"{j+1:04d}"
                
                # For additional CLINs, ensure at most one FAT and one PVT
                if j == 1:
                    item_type = random.choice(['FAT', 'PVT'])
                elif j == 2:
                    item_type = 'Production' if item_type == 'FAT' else 'Production'
                else:
                    item_type = 'Production'
                
                # Generate CLIN data
                order_qty = random.randint(1, 100)
                unit_price = round(random.uniform(100, 1000), 2)
                item_value = round(order_qty * unit_price, 2)
                contract_value += item_value
                
                # Mix of real and made-up NSNs
                if real_nsns and random.random() > 0.3:  # 70% chance to use real NSN
                    nsn, nsn_description = random.choice(real_nsns)
                else:
                    nsn = f"TEST{i+1:03d}{j+1:02d}"  # Format as TEST00101, TEST00102, etc.
                    nsn_description = f"Test NSN Description {i+1}{j+1}"
                
                ia = random.choice(['O', 'D'])
                fob = random.choice(['O', 'D'])
                clin_due_date = (award_date + timedelta(days=random.randint(30, 90))).strftime('%Y-%m-%d')
                
                # Randomly decide if this CLIN should have supplier data (about 30% won't)
                has_supplier = random.random() > 0.3
                
                if has_supplier and real_suppliers and random.random() > 0.3:  # 70% chance to use real supplier
                    supplier = random.choice(real_suppliers)
                elif has_supplier:
                    supplier = f"Test Supplier {i+1:03d}{j+1:02d}"  # Format as TEST00101, TEST00102, etc.
                else:
                    supplier = ''
                
                if has_supplier and supplier:
                    supplier_due_date = (award_date + timedelta(days=random.randint(15, 45))).strftime('%Y-%m-%d')
                    supplier_unit_price = round(unit_price * random.uniform(0.8, 1.2), 2)
                    supplier_price = round(supplier_unit_price * order_qty, 2)
                    supplier_payment_terms = random.choice(['Net 30', 'Net 45', 'Net 60'])
                else:
                    supplier_due_date = ''
                    supplier_unit_price = ''
                    supplier_price = ''
                    supplier_payment_terms = ''
                
                # Add CLIN data
                clin_data.append([
                    contract_number,
                    buyer,
                    award_date_str,
                    due_date,
                    contract_value,  # Will be updated after all CLINs
                    contract_type,
                    solicitation_type,
                    item_number,
                    item_type,
                    nsn,
                    nsn_description,
                    ia,
                    fob,
                    clin_due_date,
                    order_qty,
                    uom,
                    item_value,
                    unit_price,
                    supplier,
                    supplier_due_date,
                    supplier_unit_price,
                    supplier_price,
                    supplier_payment_terms
                ])
            
            # Update contract value in all CLINs for this contract
            for clin in clin_data:
                clin[4] = contract_value  # Update contract value
                writer.writerow(clin)
        
        return response
    
    except Exception as e:
        # Log the error and return a generic error message
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error generating test data: {str(e)}")
        return HttpResponse("Error generating test data. Please check the logs for details.", status=500)

@login_required
@require_http_methods(["POST"])
def scan_sharepoint_status(request):
    """
    Read-only SharePoint check for one or all queued contracts.
    Body JSON: {"queue_id": 123} for a single record, or {"all": true} for all unconfirmed.
    Updates sharepoint_folder_status, sharepoint_folder_url, and award_pdf_status on each record.
    """
    from users.sharepoint_services import check_contract_sharepoint_status

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError, ValueError):
        body = {}

    queue_id = body.get("queue_id")
    scan_all = body.get("all")

    if queue_id:
        contracts = QueueContract.objects.filter(pk=queue_id, contract_number__isnull=False).exclude(contract_number="")
    elif scan_all:
        contracts = QueueContract.objects.filter(
            contract_number__isnull=False
        ).exclude(contract_number="").filter(
            models.Q(sharepoint_folder_status__in=["pending", "error"]) |
            models.Q(award_pdf_status__in=["pending", "error"])
        )
    else:
        return JsonResponse({"error": "Provide queue_id or all=true"}, status=400)

    results = []
    for qc in contracts:
        try:
            status = check_contract_sharepoint_status(qc)
            results.append({
                "queue_id": qc.pk,
                "contract_number": qc.contract_number,
                "folder_status": qc.sharepoint_folder_status,
                "folder_url": qc.sharepoint_folder_url or "",
                "pdf_status": qc.award_pdf_status,
                "folder_exists": status["folder_exists"],
                "pdf_exists": status["pdf_exists"],
            })
        except Exception as exc:
            logger.warning("SharePoint scan failed for queue %s: %s", qc.pk, exc)
            results.append({
                "queue_id": qc.pk,
                "contract_number": qc.contract_number,
                "error": str(exc)[:200],
            })

    return JsonResponse({"results": results})


def save_to_sharepoint(pdf_file, queue_contract):
    """
    Create the contract folder in SharePoint and upload the award PDF.
    Failure is non-fatal: status fields on queue_contract are updated to reflect the outcome.
    """
    if not queue_contract or not queue_contract.contract_number:
        return
    from users.sharepoint_services import ensure_contract_folder, upload_award_pdf_to_sharepoint
    try:
        folder_url, folder_existed = ensure_contract_folder(queue_contract)
        queue_contract.sharepoint_folder_status = "exists" if folder_existed else "created"
        queue_contract.sharepoint_folder_url = folder_url
        queue_contract.save(update_fields=["sharepoint_folder_status", "sharepoint_folder_url"])
        upload_award_pdf_to_sharepoint(pdf_file, queue_contract)
        queue_contract.award_pdf_status = "uploaded"
        queue_contract.save(update_fields=["award_pdf_status"])
    except Exception as exc:
        logger.warning(
            "SharePoint save failed for %s: %s",
            queue_contract.contract_number,
            exc,
        )
        queue_contract.sharepoint_folder_status = "error"
        queue_contract.sharepoint_notes = str(exc)[:500]
        queue_contract.award_pdf_status = "error"
        queue_contract.save(
            update_fields=["sharepoint_folder_status", "sharepoint_notes", "award_pdf_status"]
        )


@login_required
def upload_award_pdf(request):
    """
    Accept one or more award PDFs under FILES key 'pdf_files', parse and ingest
    into QueueContract/QueueClin. Returns per-file JSON results.
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    files = request.FILES.getlist("pdf_files")
    results = []

    for pdf_file in files:
        filename = getattr(pdf_file, "name", "") or "unknown"
        parse_result = None
        try:
            if not str(filename).lower().endswith(".pdf"):
                results.append(
                    {
                        "filename": filename,
                        "contract_number": None,
                        "pdf_parse_status": "error",
                        "pdf_parse_notes": f"{filename} is not a valid award document, no contract was created.",
                        "was_existing_record": False,
                    }
                )
                continue

            parse_result = parse_award_pdf(pdf_file)

            was_existing = False
            if parse_result.contract_number:
                was_existing = QueueContract.objects.filter(
                    contract_number=parse_result.contract_number
                ).exists()

            with transaction.atomic():
                queue_contract = ingest_parsed_award(
                    parse_result, user=request.user
                )

            save_to_sharepoint(pdf_file, queue_contract)

            results.append(
                {
                    "filename": filename,
                    "contract_number": queue_contract.contract_number,
                    "pdf_parse_status": queue_contract.pdf_parse_status,
                    "pdf_parse_notes": queue_contract.pdf_parse_notes or "",
                    "was_existing_record": was_existing,
                }
            )
        except Exception as exc:
            logger.exception("upload_award_pdf failed for %s", filename)
            contract_number = (
                getattr(parse_result, "contract_number", None)
                if parse_result is not None
                else None
            )
            results.append(
                {
                    "filename": filename,
                    "contract_number": contract_number,
                    "pdf_parse_status": "error",
                    "pdf_parse_notes": str(exc),
                    "was_existing_record": False,
                }
            )

    return JsonResponse({"results": results})


@require_http_methods(["POST"])
@login_required
def upload_csv(request):
    """Upload and process a CSV file for contract queue"""
    print("=== Starting CSV Upload Process ===")
    if 'csv_file' not in request.FILES:
        print("No file uploaded")
        return JsonResponse({
            'success': False,
            'error': 'No file uploaded',
            'error_type': 'missing_file'
        })
    
    try:
        csv_file = request.FILES['csv_file']
        print(f"Processing file: {csv_file.name}")
        
        # Validate file type
        if not csv_file.name.endswith('.csv'):
            print("Invalid file type")
            return JsonResponse({
                'success': False,
                'error': 'Invalid file type. Please upload a CSV file.',
                'error_type': 'invalid_file_type'
            })
        
        try:
            csv_data = csv_file.read().decode('utf-8')
            print("File successfully decoded as UTF-8")
        except UnicodeDecodeError as e:
            print(f"File decoding error: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'Invalid file encoding. Please ensure the CSV file is saved with UTF-8 encoding.',
                'error_type': 'encoding_error'
            })
        
        # Create a list to store all rows for processing
        csv_rows = list(csv.DictReader(StringIO(csv_data)))
        print(f"CSV Headers: {csv_rows[0].keys() if csv_rows else []}")
        
        # Validate required columns
        required_columns = [
            'Contract Number', 'Buyer', 'Award Date', 'Due Date', 'Contract Value',
            'Contract Type', 'Solicitation Type', 'Item Number', 'Item Type', 'NSN',
            'NSN Description', 'Order Qty', 'UOM', 'Unit Price'
        ]
        
        missing_columns = [col for col in required_columns if col not in (csv_rows[0].keys() if csv_rows else [])]
        if missing_columns:
            print(f"Missing columns: {missing_columns}")
            return JsonResponse({
                'success': False,
                'error': f'Missing required columns: {", ".join(missing_columns)}',
                'error_type': 'missing_columns',
                'missing_columns': missing_columns
            })

        # First, check all contract numbers and identify duplicates
        print("\n=== Checking For Duplicate Contracts ===")
        duplicate_contracts = set()
        contract_numbers = set()
        
        # First pass: collect all unique contract numbers from CSV and check for duplicates
        for contract_number in {row['Contract Number'] for row in csv_rows}:
            # Check Contract table
            if Contract.objects.filter(contract_number=contract_number).exists():
                duplicate_contracts.add(contract_number)
                print(f"Found duplicate in Contract table: {contract_number}")
                continue
            
            # Check QueueContract table
            if QueueContract.objects.filter(contract_number=contract_number).exists():
                duplicate_contracts.add(contract_number)
                print(f"Found duplicate in QueueContract table: {contract_number}")
        
        # Track statistics for final message
        total_contracts = len({row['Contract Number'] for row in csv_rows})
        duplicate_count = len(duplicate_contracts)
        processed_count = 0
        
        print(f"\nFound {duplicate_count} duplicate contracts out of {total_contracts} total")

        # Continue with processing non-duplicate contracts
        with transaction.atomic():
            current_contract = None
            
            for row_number, row in enumerate(csv_rows, 1):
                contract_number = row['Contract Number']
                
                # Skip this row if it's for a duplicate contract
                if contract_number in duplicate_contracts:
                    print(f"Skipping duplicate contract: {contract_number}")
                    continue
                
                print(f"\nProcessing row {row_number}")
                print(f"Contract Number: {contract_number}")
                
                try:
                    # If this is a new contract
                    if not current_contract or current_contract.contract_number != contract_number:
                        print(f"Creating new contract: {contract_number}")
                        
                        # Process date fields
                        try:
                            award_date = timezone.make_aware(datetime.strptime(row['Award Date'], '%Y-%m-%d')) if row['Award Date'] else None
                            due_date = timezone.make_aware(datetime.strptime(row['Due Date'], '%Y-%m-%d')) if row['Due Date'] else None
                            print(f"Dates processed - Award: {award_date}, Due: {due_date}")
                        except ValueError as e:
                            print(f"Date parsing error: {str(e)}")
                            return JsonResponse({
                                'success': False,
                                'error': f'Invalid date format in row {row_number}. Please use YYYY-MM-DD format.',
                                'error_type': 'date_format_error'
                            })
                        
                        # Process contract value
                        try:
                            contract_value = Decimal(row['Contract Value'].replace(',', '').replace('$', '')) if row['Contract Value'] else None
                            print(f"Contract value processed: {contract_value}")
                        except InvalidOperation as e:
                            print(f"Contract value parsing error: {str(e)}")
                            return JsonResponse({
                                'success': False,
                                'error': f'Invalid contract value in row {row_number}. Please enter a valid number.',
                                'error_type': 'decimal_format_error'
                            })
                        
                        # Create contract
                        try:
                            csv_type = (row.get('Contract Type') or '').strip()
                            current_contract = QueueContract.objects.create(
                                contract_number=contract_number,
                                buyer=row['Buyer'],
                                award_date=award_date,
                                due_date=due_date,
                                contract_value=contract_value,
                                contract_type=detect_contract_type(contract_number) or csv_type or None,
                                solicitation_type=row['Solicitation Type'],
                                created_by=request.user,
                                modified_by=request.user
                            )
                            processed_count += 1
                            print(f"Contract created successfully with ID: {current_contract.id}")
                        except Exception as e:
                            print(f"Contract creation error: {str(e)}")
                            raise
                    
                    # Create CLIN
                    print(f"Creating CLIN for contract {current_contract.contract_number}, Item Number: {row['Item Number']}")
                    try:
                        QueueClin.objects.create(
                            contract_queue=current_contract,
                            item_number=row['Item Number'],
                            item_type=row['Item Type'],
                            nsn=row['NSN'],
                            nsn_description=row['NSN Description'],
                            ia=row.get('IA', ''),
                            fob=row.get('FOB', ''),
                            due_date=timezone.make_aware(datetime.strptime(row['Due Date'], '%Y-%m-%d')) if row['Due Date'] else None,
                            order_qty=Decimal(row['Order Qty'].replace(',', '')) if row['Order Qty'] else None,
                            uom=row['UOM'],
                            item_value=Decimal(row['Item Value'].replace(',', '').replace('$', '')) if row.get('Item Value') else None,
                            unit_price=Decimal(row['Unit Price'].replace(',', '').replace('$', '')) if row['Unit Price'] else None,
                            supplier=row.get('Supplier', ''),
                            supplier_due_date=timezone.make_aware(datetime.strptime(row['Supplier Due Date'], '%Y-%m-%d')) if row.get('Supplier Due Date') else None,
                            supplier_unit_price=Decimal(row['Supplier Unit Price'].replace(',', '').replace('$', '')) if row.get('Supplier Unit Price') else None,
                            supplier_price=Decimal(row['Supplier Price'].replace(',', '').replace('$', '')) if row.get('Supplier Price') else None,
                            supplier_payment_terms=row.get('Supplier Payment Terms', ''),
                            created_by=request.user,
                            modified_by=request.user
                        )
                        print("CLIN created successfully")
                    except Exception as e:
                        print(f"CLIN creation error: {str(e)}")
                        raise
                        
                except Exception as e:
                    print(f"Error processing row {row_number}: {str(e)}")
                    import traceback
                    print(f"Traceback: {traceback.format_exc()}")
                    return JsonResponse({
                        'success': False,
                        'error': f'Error processing row {row_number}: {str(e)}',
                        'error_type': 'processing_error',
                        'traceback': traceback.format_exc()
                    })
            
            # Prepare result message
            result_message = f'CSV processing completed. '
            if processed_count > 0:
                result_message += f'Successfully imported {processed_count} contract(s). '
            if duplicate_count > 0:
                result_message += f'Skipped {duplicate_count} duplicate contract(s): \n'
                for dup in duplicate_contracts:
                    result_message += f"\n{dup}"
            
            print("\n=== CSV Upload Process Completed ===")
            return JsonResponse({
                'success': True,
                'message': result_message,
                'processed_count': processed_count,
                'duplicate_count': duplicate_count,
                'duplicate_contracts': list(duplicate_contracts)
            })
            
    except Exception as e:
        print("\n=== CSV Upload Process Failed ===")
        print(f"Error: {str(e)}")
        import traceback
        tb = traceback.format_exc()
        print(f"Traceback: {tb}")
        return JsonResponse({
            'success': False,
            'error': f'Error processing CSV file: {str(e)}',
            'error_type': 'general_error',
            'traceback': tb
        })

def validate_contract_number(request, contract_number):
    """
    Validates if a contract number already exists in either the Contract or QueueContract tables.
    Returns a JSON response indicating whether the contract number is available.
    """
    try:
        print(f"Validating contract number: {contract_number}")
        Contract.objects.get(contract_number=contract_number)
        print(f"Contract number {contract_number} found in Contract table")
        return JsonResponse({
            'success': False,
            'message': f'Contract number "{contract_number}" already exists in the Contract table.',
            'error_type': 'duplicate_contract'
        })
    except Contract.DoesNotExist:
        try:
            QueueContract.objects.get(contract_number=contract_number)
            print(f"Contract number {contract_number} found in QueueContract table")
            return JsonResponse({
                'success': False,
                'message': f'Contract number "{contract_number}" already exists in the QueueContract table.',
                'error_type': 'duplicate_queue_contract'
            })
        except QueueContract.DoesNotExist:
            print(f"Contract number {contract_number} is available")
            return JsonResponse({
                'success': True,
                'message': f'Contract number "{contract_number}" is available.'
            })
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"Error validating contract number: {str(e)}\nTraceback: {tb}")
        return JsonResponse({
            'success': False,
            'message': f'An unexpected error occurred: {str(e)}',
            'error_type': 'validation_error',
            'traceback': tb
        })

def _queue_clin_item_key(item_number):
    """Normalize CLIN line number for collision checks between queue rows."""
    if item_number is None:
        return ''
    return str(item_number).strip()


def _orphan_char_wins(value):
    """True if orphan should overwrite a string field (non-null and non-blank)."""
    if value is None:
        return False
    return str(value).strip() != ''


def _coalesce_queue_contract_header_from_orphan(orphan, target, user):
    """Orphan wins per field: set target from orphan only when orphan has a value."""
    for fname in (
        'buyer',
        'contract_type',
        'idiq_number',
        'contractor_name',
        'contractor_cage',
    ):
        v = getattr(orphan, fname, None)
        if _orphan_char_wins(v):
            setattr(target, fname, v)
    if orphan.award_date is not None:
        target.award_date = orphan.award_date
    if orphan.due_date is not None:
        target.due_date = orphan.due_date
    if orphan.contract_value is not None:
        target.contract_value = orphan.contract_value
    target.modified_by = user


def _merged_pdf_parse_notes_for_queue_contract(target_notes, orphan_notes):
    """Preserve both sides' notes and append merge audit line."""
    parts = []
    if (target_notes or '').strip():
        parts.append(str(target_notes).strip())
    if (orphan_notes or '').strip():
        parts.append(str(orphan_notes).strip())
    parts.append('Data merged from orphaned PDF record.')
    return '\n\n'.join(parts)


def _copy_queue_clin_payload(source, target, user):
    """Copy data fields from orphan QueueClin onto target (orphan wins). Does not change PK or item_number."""
    field_names = [
        'item_type', 'nsn', 'nsn_description', 'ia', 'fob', 'due_date',
        'order_qty', 'item_value', 'unit_price', 'uom',
        'supplier', 'supplier_due_date', 'supplier_unit_price', 'supplier_price',
        'supplier_payment_terms', 'matched_nsn', 'matched_supplier',
    ]
    for name in field_names:
        setattr(target, name, getattr(source, name))
    target.modified_by = user
    target.save()


@login_required
@require_POST
def match_contract_number(request, queue_id):
    """Attach orphaned queue rows (no contract_number) to an existing queue contract or set the number.

    Uses select_for_update on the orphan and, when merging, the target row to avoid double-merge races.
    """
    target_raw = (request.POST.get('target_contract_number') or '').strip()
    if not target_raw:
        messages.error(request, 'Please enter a contract number.')
        return redirect('processing:queue')

    with transaction.atomic():
        orphan = (
            QueueContract.objects.select_for_update()
            .filter(pk=queue_id)
            .first()
        )
        if not orphan:
            messages.error(request, 'Queue item not found.')
            return redirect('processing:queue')

        if orphan.contract_number is not None:
            messages.error(
                request,
                'This queue item already has a contract number; match is only for orphaned rows.',
            )
            return redirect('processing:queue')

        if orphan.is_being_processed:
            messages.error(
                request,
                'Cannot match while this item is being processed. Cancel or finish processing first.',
            )
            return redirect('processing:queue')

        if ProcessContract.objects.filter(queue_id=queue_id).exists():
            messages.error(
                request,
                'A processing session exists for this queue item; cancel it before matching.',
            )
            return redirect('processing:queue')

        existing = (
            QueueContract.objects.select_for_update()
            .filter(
                company_id=orphan.company_id,
                contract_number=target_raw,
            )
            .exclude(pk=orphan.pk)
            .first()
        )

        if existing:
            orphan_clins = list(orphan.clins.select_for_update().all())
            target_clins = list(existing.clins.select_for_update().all())
            by_item_key = {}
            for tc in target_clins:
                k = _queue_clin_item_key(tc.item_number)
                if k not in by_item_key:
                    by_item_key[k] = []
                by_item_key[k].append(tc)

            for o_clin in orphan_clins:
                key = _queue_clin_item_key(o_clin.item_number)
                bucket = by_item_key.get(key) if key else None
                if bucket:
                    t_clin = bucket.pop(0)
                    _copy_queue_clin_payload(o_clin, t_clin, request.user)
                    o_clin.delete()
                else:
                    o_clin.contract_queue = existing
                    o_clin.company_id = existing.company_id
                    o_clin.modified_by = request.user
                    o_clin.save()

            _coalesce_queue_contract_header_from_orphan(orphan, existing, request.user)
            existing.pdf_parse_status = 'success'
            existing.pdf_parsed_at = orphan.pdf_parsed_at
            existing.pdf_parse_notes = _merged_pdf_parse_notes_for_queue_contract(
                existing.pdf_parse_notes,
                orphan.pdf_parse_notes,
            )
            existing.save()

            orphan.delete()
            messages.success(
                request,
                f'Merged orphaned PDF data into queue contract {target_raw}.',
            )
        else:
            orphan.contract_number = target_raw
            orphan.pdf_parse_status = 'success'
            orphan.pdf_parse_notes = None
            orphan.modified_by = request.user
            orphan.save()
            messages.success(
                request,
                f'Contract number set to {target_raw}.',
            )

    return redirect('processing:queue')


@login_required
@require_POST
def delete_queue_contract(request, queue_id):
    """Delete a contract from the queue"""
    try:
        queue_contract = get_object_or_404(QueueContract, id=queue_id)
        
        # Only superusers can delete contracts
        if not request.user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'Only superusers can delete contracts'
            }, status=403)
            
        # Check if contract is being processed
        if queue_contract.is_being_processed:
            return JsonResponse({
                'success': False,
                'error': 'Cannot delete a contract that is being processed'
            }, status=400)
            
        # Delete associated process contract if it exists
        p_contract = ProcessContract.objects.filter(queue_id=queue_id).first()
        if p_contract:
            p_contract.delete()
        
        # Delete the queue contract
        queue_contract.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'Contract deleted successfully'
        })
        
    except QueueContract.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Contract not found'
        }, status=404)
    except Exception as e:
        logger.exception("Error deleting queue contract")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ---------------------------------------------------------------------------
# IDIQ Processing views
# ---------------------------------------------------------------------------

def _unpack_idiq_meta(description: str) -> dict:
    """Unpack IDIQ_META shadow-schema string from ProcessContract.description."""
    result = {'term_months': None, 'max_value': None, 'min_guarantee': None}
    if not description or not description.startswith('IDIQ_META'):
        return result
    for part in description.split('|')[1:]:
        if part.startswith('TERM:'):
            try:
                result['term_months'] = int(part[5:])
            except ValueError:
                pass
        elif part.startswith('MAX:'):
            try:
                result['max_value'] = Decimal(part[4:])
            except InvalidOperation:
                pass
        elif part.startswith('MIN:'):
            try:
                result['min_guarantee'] = Decimal(part[4:])
            except InvalidOperation:
                pass
    return result


@login_required
def idiq_processing_edit(request, process_contract_id):
    """IDIQ contract processing and editing page."""
    process_contract = get_object_or_404(ProcessContract, id=process_contract_id)
    meta = _unpack_idiq_meta(process_contract.description or '')
    term_months = meta['term_months']
    clins = process_contract.clins.all().order_by('item_number')
    context = {
        'process_contract': process_contract,
        'clins': clins,
        'idiq_term_months': term_months,
        'idiq_term_years': (term_months / 12) if term_months else None,
        'idiq_max_value': meta['max_value'],
        'idiq_min_guarantee': meta['min_guarantee'],
    }
    return render(request, 'processing/idiq_processing_edit.html', context)


@login_required
@require_POST
@transaction.atomic
def finalize_idiq_contract(request, process_contract_id):
    """Create IdiqContract + IdiqContractDetails from a matched IDIQ ProcessContract."""
    try:
        process_contract = get_object_or_404(ProcessContract, id=process_contract_id)
        clins = list(process_contract.clins.all())

        # Validate each CLIN is fully matched
        for pc in clins:
            if not pc.nsn:
                return JsonResponse({'success': False, 'error': f'NSN must be matched for CLIN {pc.item_number}'})
            if not pc.supplier:
                return JsonResponse({'success': False, 'error': f'Supplier must be matched for CLIN {pc.item_number}'})

        # Read header values from POST
        try:
            term_months = int(request.POST.get('term_months') or 0) or None
        except (ValueError, TypeError):
            term_months = None

        try:
            max_value = Decimal(request.POST.get('max_value', ''))
        except InvalidOperation:
            max_value = None

        try:
            min_guarantee = Decimal(request.POST.get('min_guarantee', ''))
        except InvalidOperation:
            min_guarantee = None

        # Create the canonical IdiqContract record
        idiq_contract = IdiqContract.objects.create(
            contract_number=process_contract.contract_number,
            buyer=process_contract.buyer,
            award_date=process_contract.award_date,
            term_length=term_months,
            max_value=max_value,
            min_guarantee=min_guarantee,
            closed=False,
            created_by=request.user,
            modified_by=request.user,
        )

        # Create one IdiqContractDetails row per CLIN
        for pc in clins:
            min_order_qty = (request.POST.get(f'min_order_qty_{pc.id}') or '').strip() or None
            IdiqContractDetails.objects.create(
                idiq_contract=idiq_contract,
                nsn=pc.nsn,
                supplier=pc.supplier,
                min_order_qty=min_order_qty,
            )

        # Cleanup: delete processing + queue records
        queue_id = process_contract.queue_id
        process_contract.delete()
        if queue_id:
            QueueContract.objects.filter(id=queue_id).delete()

        return JsonResponse({
            'success': True,
            'idiq_contract_id': idiq_contract.id,
            'message': 'IDIQ contract finalized successfully',
        })

    except Exception as e:
        logger.exception("Error finalizing IDIQ contract %s", process_contract_id)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
