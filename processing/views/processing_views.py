from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import DetailView, UpdateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.forms import inlineformset_factory
from processing.models import ProcessContract, ProcessClin, QueueContract, QueueClin, SequenceNumber
from processing.forms import ProcessContractForm, ProcessClinForm
from contracts.models import Contract, Clin, Buyer, Nsn, Supplier, IdiqContract, ClinType, SpecialPaymentTerms, ContractType, SalesClass
import csv
import os
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy, reverse
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_http_methods
from django.http import Http404
import json

@login_required
@require_http_methods(["POST"])
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
                    po_num_ext=clin_data.po_num_ext if hasattr(clin_data, 'po_num_ext') else None,
                    tab_num=new_tab_number,
                    clin_po_num=new_po_number,
                    po_number=new_po_number,
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
        if self.request.POST:
            context['clin_formset'] = ProcessClinFormSet(
                self.request.POST,
                instance=self.object
            )
        else:
            context['clin_formset'] = ProcessClinFormSet(instance=self.object)
            
        # Add all IDIQ contracts to the context
        context['idiq_contracts'] = IdiqContract.objects.filter(closed=False).order_by('contract_number')

        # Add all CLIN types to the context
        context['clin_types'] = ClinType.objects.all().order_by('description')

        # Add all Contract types to the context
        context['contract_types'] = ContractType.objects.all().order_by('description')

        # Add all special payment terms to the context
        context['special_payment_terms'] = SpecialPaymentTerms.objects.all().order_by('code')

        # Add all sales classes to the context
        context['sales_classes'] = SalesClass.objects.all().order_by('sales_team')
        
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
    """Match an NSN based on ID"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)
    
    try:
        data = json.loads(request.body)
        nsn_id = data.get('id')
        
        if not nsn_id:
            return JsonResponse({'error': 'No NSN ID provided'}, status=400)
        
        process_clin = ProcessClin.objects.get(id=process_clin_id)
        nsn = Nsn.objects.get(id=nsn_id)
        
        # Update all NSN fields using the correct field names
        process_clin.nsn = nsn
        process_clin.nsn_text = nsn.nsn_code
        process_clin.nsn_description_text = nsn.description
        process_clin.save()
        
        return JsonResponse({
            'success': True,
            'nsn_id': nsn.id,
            'nsn_number': nsn.nsn_code,
            'nsn_description': nsn.description
        })
    except ProcessClin.DoesNotExist:
        return JsonResponse({
            'error': 'Process CLIN not found'
        }, status=404)
    except Nsn.DoesNotExist:
        return JsonResponse({
            'error': 'NSN not found'
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
def match_supplier(request, process_clin_id):
    """Match a supplier based on ID"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)
    
    try:
        data = json.loads(request.body)
        supplier_id = data.get('supplier_id')
        
        if not supplier_id:
            return JsonResponse({'error': 'No supplier ID provided'}, status=400)
        
        process_clin = ProcessClin.objects.get(id=process_clin_id)
        supplier = Supplier.objects.get(id=supplier_id)
        
        # Update all supplier fields
        process_clin.supplier = supplier
        process_clin.supplier_text = supplier.name
        process_clin.save()
        
        return JsonResponse({
            'success': True,
            'supplier_id': supplier.id,
            'supplier_name': supplier.name
        })
    except ProcessClin.DoesNotExist:
        return JsonResponse({
            'error': 'Process CLIN not found'
        }, status=404)
    except Supplier.DoesNotExist:
        return JsonResponse({
            'error': 'Supplier not found'
        }, status=404)
    except json.JSONDecodeError:
        return JsonResponse({
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)

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
            buyer=process_contract.buyer,
            award_date=process_contract.award_date,
            due_date=process_contract.due_date,
            contract_value=process_contract.contract_value,
            description=process_contract.description,
            created_by=request.user,
            modified_by=request.user
        )
        
        # Create CLINs
        for process_clin in process_contract.clins.all():
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
            
            Clin.objects.create(
                contract=contract,
                clin_number=process_clin.item_number,
                nsn=process_clin.nsn,
                supplier=process_clin.supplier,
                quantity=process_clin.order_qty,
                unit_price=process_clin.unit_price,
                total_price=process_clin.item_value,
                description=process_clin.description,
                ia=process_clin.ia,
                fob=process_clin.fob,
                due_date=process_clin.due_date,
                supplier_due_date=process_clin.supplier_due_date,
                price_per_unit=process_clin.price_per_unit,
                quote_value=process_clin.quote_value,
                created_by=request.user,
                modified_by=request.user,
                planned_split=process_clin.planned_split,
                plan_gross=process_clin.plan_gross
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
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

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

# Create formset for CLINs
ProcessClinFormSet = inlineformset_factory(
    ProcessContract,
    ProcessClin,
    form=ProcessClinForm,
    extra=1,
    can_delete=True
)

def download_csv_template(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="contract_template.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Contract Number',
        'Buyer',
        'Award Date',
        'Due Date',
        'Contract Value',
        'Description',
        'CLIN Number',
        'NSN',
        'NSN Description',
        'Supplier',
        'Quantity',
        'Unit Price',
        'Total Price',
        'CLIN Description'
    ])
    
    return response

def download_test_data(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="test_contracts.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Contract Number',
        'Buyer',
        'Award Date',
        'Due Date',
        'Contract Value',
        'Description',
        'CLIN Number',
        'NSN',
        'NSN Description',
        'Supplier',
        'Quantity',
        'Unit Price',
        'Total Price',
        'CLIN Description'
    ])
    
    # Add some test data
    writer.writerow([
        'TEST-2024-001',
        'Test Buyer 1',
        '2024-01-01',
        '2024-12-31',
        '100000.00',
        'Test Contract 1',
        '0001',
        '1234-56-789-0123',
        'Test NSN Description 1',
        'Test Supplier 1',
        '10',
        '1000.00',
        '10000.00',
        'Test CLIN Description 1'
    ])
    
    return response

def upload_csv(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        if not csv_file.name.endswith('.csv'):
            return JsonResponse({'success': False, 'error': 'Please upload a CSV file'})
        
        try:
            decoded_file = csv_file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file)
            
            for row in reader:
                # Create QueueContract entry
                contract = QueueContract.objects.create(
                    contract_number=row['Contract Number'],
                    buyer=row['Buyer'],
                    award_date=row['Award Date'],
                    due_date=row['Due Date'],
                    contract_value=row['Contract Value'],
                    description=row['Description']
                )
                
                # Create QueueClin entries
                clin = contract.clins.create(
                    clin_number=row['CLIN Number'],
                    nsn=row['NSN'],
                    nsn_description=row['NSN Description'],
                    supplier=row['Supplier'],
                    quantity=row['Quantity'],
                    unit_price=row['Unit Price'],
                    total_price=row['Total Price'],
                    description=row['CLIN Description']
                )
            
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})

def get_process_contract(request, queue_id):
    """Get the process contract ID for a queue item to resume processing"""
    try:
        queue_item = get_object_or_404(QueueContract, id=queue_id)
        process_contract = ProcessContract.objects.filter(queue_id=queue_id).first()
        
        if process_contract:
            return JsonResponse({
                'success': True,
                'process_contract_id': process_contract.id
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'No processing contract found for this queue item'
            })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }) 