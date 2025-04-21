from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import DetailView, UpdateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.forms import inlineformset_factory
from processing.models import ProcessContract, ProcessClin, QueueContract, QueueClin, SequenceNumber, ProcessContractSplit
from processing.forms import ProcessContractForm, ProcessClinForm, ProcessClinFormSet
from contracts.models import Contract, Clin, Buyer, Nsn, Supplier, IdiqContract, ClinType, SpecialPaymentTerms, ContractType, SalesClass, PaymentHistory, ContractSplit, ContractStatus
import csv
import os
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
from decimal import Decimal

logger = logging.getLogger(__name__)

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

        #Get next po_number and tab_num from the sequence table
        new_po_number = SequenceNumber.get_po_number()
        new_tab_number = SequenceNumber.get_tab_number()
        SequenceNumber.advance_po_number()
        SequenceNumber.advance_tab_number()
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
            files_url='\\STATZFS01\public\CJ_Data\data\V87\aFed-DOD\Contract ' + queue_item.contract_number,
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
                item_number=process_clin.item_number,
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
                    item_number=row['CLIN Number'],
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

@login_required
@require_POST
@transaction.atomic
def cancel_processing(request, process_contract_id):
    """Cancel processing of a contract and reset its status"""
    try:
        with transaction.atomic():
            process_contract = get_object_or_404(ProcessContract, id=process_contract_id)
            
            # Get associated queue contract
            queue_contract = QueueContract.objects.get(id=process_contract.queue_id)
            
            # Reset queue contract status
            queue_contract.is_being_processed = False
            queue_contract.processed_by = None
            queue_contract.processing_started = None
            queue_contract.status = 'ready_for_processing'
            queue_contract.save()
            
            # Delete the process contract
            process_contract.delete()
            
            return JsonResponse({
                'success': True,
                'message': 'Processing cancelled successfully'
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

@login_required
@require_POST
@transaction.atomic
def cancel_process_contract(request, process_contract_id):
    """
    Cancel a process contract and return to queue
    """
    try:
        with transaction.atomic():
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
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

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
        'special_payment_terms': SpecialPaymentTerms.objects.all().order_by('code'),
    }
    return render(request, 'processing/process_contract_form.html', context)

@require_http_methods(["POST"])
def create_split_view(request):
    try:
        data = json.loads(request.body)
        split = ProcessContractSplit.create_split(
            process_contract_id=data['process_contract_id'],
            company_name=data['company_name'],
            split_value=data['split_value']
        )
        return JsonResponse({
            'success': True,
            'split_id': split.id
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@require_http_methods(["POST"])
def update_split_view(request, split_id):
    try:
        data = json.loads(request.body)
        split = ProcessContractSplit.update_split(
            contract_split_id=split_id,
            company_name=data.get('company_name'),
            split_value=data.get('split_value'),
            split_paid=data.get('split_paid')
        )
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@require_http_methods(["POST"])
def delete_split_view(request, split_id):
    try:
        success = ProcessContractSplit.delete_split(split_id)
        return JsonResponse({'success': success})
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

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
        
        # Validate required fields
        validation_errors = {}
        
        # Contract-level validations
        required_fields = [
            'contract_number', 'po_number', 'tab_num', 'contract_type',
            'buyer', 'award_date', 'contract_value'
        ]
        for field in required_fields:
            if not getattr(process_contract, field):
                validation_errors[field] = f'{field.replace("_", " ").title()} is required'
        
        # CLIN validations
        clin_errors = []
        process_clins = ProcessClin.objects.filter(process_contract=process_contract)
        
        if not process_clins.exists():
            validation_errors['clins'] = 'At least one CLIN is required'
        else:
            for clin in process_clins:
                clin_error = {}
                required_clin_fields = [
                    'item_value', 'quote_value', 'item_number',
                    'nsn', 'supplier', 'order_qty', 'unit_price'
                ]
                for field in required_clin_fields:
                    if not getattr(clin, field):
                        clin_error[field] = f'{field.replace("_", " ").title()} is required'
                if clin_error:
                    clin_error['item_number'] = clin.item_number or 'Unknown CLIN'
                    clin_errors.append(clin_error)
        
        if clin_errors:
            validation_errors['clins'] = clin_errors
            
        if validation_errors:
            return JsonResponse({
                'success': False,
                'validation_errors': validation_errors
            }, status=400)
            
            
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
            created_by=request.user,
            modified_by=request.user,
            status=ContractStatus.objects.get(id=1)  # Use the ContractStatus instance with ID=1
        )
        
        # Create CLINs and payment history with all relevant fields
        for process_clin in process_clins:
            clin = Clin.objects.create(
                contract=contract,
                open=True,
                closed=False,
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
            
            # Create payment history records
            PaymentHistory.objects.create(
                clin=clin,
                payment_type='item_value',
                payment_amount=process_clin.item_value,
                payment_date=process_contract.award_date,
                payment_info='Initial item value',
                created_by=request.user,
                updated_by=request.user
            )
            PaymentHistory.objects.create(
                clin=clin,
                payment_type='quote_value',
                payment_amount=process_clin.quote_value,
                payment_date=process_contract.award_date,
                payment_info='Initial quote value',
                created_by=request.user,
                updated_by=request.user
            )
            
        # Create contract splits
        for process_split in ProcessContractSplit.objects.filter(process_contract=process_contract):
            ContractSplit.objects.create(
                contract=contract,
                company_name=process_split.company_name,
                split_value=process_split.split_value,
                split_paid=process_split.split_paid or Decimal('0.00'),
            )
            
        # Update queue contract status if it exists
        if process_contract.queue_id:
            try:
                queue_contract = QueueContract.objects.get(id=process_contract.queue_id)
                queue_contract.status = 'completed'
                queue_contract.is_being_processed = False
                queue_contract.save()
            except QueueContract.DoesNotExist:
                pass  # Queue contract might have been deleted
            
        
        email_subject = f"New Contract: {contract.contract_number}"
        email_body = (
            f"A new Contract has been created\n\n"
            f"Tab #: {contract.tab_num}\n"
            f"PO #: {contract.po_number}\n"
            f"Contract #: {contract.contract_number}\n"
            f"{contract.files_url}"
        )
        
        # Create mailto URL
        mailto_url = (
            f"mailto:?subject={quote(email_subject)}&"
            f"body={quote(email_body)}"
            f"to=dmani@statzcorp.com"
        )
        
        # Delete the process contract
        process_contract.delete()
        
        return JsonResponse({
            'success': True,
            'mailto_url': mailto_url,
            'contract_id': contract.id,
            'message': 'Contract finalized successfully'
        })
        
    except Exception as e:
        logger.exception("Error finalizing contract")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_POST
def save_contract_data(request, process_contract_id):
    """
    Simple view for auto-saving contract data without redirecting.
    Used for background saves during editing.
    """
    try:
        process_contract = get_object_or_404(ProcessContract, id=process_contract_id)
        
        # Get the form data
        form = ProcessContractForm(request.POST, instance=process_contract)
        clin_formset = ProcessClinFormSet(request.POST, instance=process_contract)
        
        # Attempt to save even with partial data for autosave
        # We don't do full validation for autosaves
        is_autosave = request.POST.get('auto_save') == 'true'
        
        if is_autosave:
            # For autosave, save what we can without strict validation
            if form.is_valid():
                process_contract = form.save()
            
            # For each valid CLIN in the formset, save it
            for clin_form in clin_formset:
                if clin_form.is_valid() and not clin_form.cleaned_data.get('DELETE', False):
                    clin_form.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Data auto-saved'
            })
        else:
            # For manual saves, use standard validation
            if form.is_valid() and clin_formset.is_valid():
                process_contract = form.save()
                clin_formset.save()
                
                return JsonResponse({
                    'success': True,
                    'message': 'Data saved successfully'
                })
            else:
                errors = {
                    'form_errors': form.errors,
                    'clin_errors': clin_formset.errors
                }
                return JsonResponse({
                    'success': False,
                    'errors': errors
                }, status=400)
                
    except Exception as e:
        logger.exception("Error saving contract data")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
    

    # From the queue_views.py file
    from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.db import transaction
from django.utils import timezone
from ..models import QueueContract, QueueClin, SequenceNumber, ProcessContract, ProcessClin, ProcessContractSplit
from contracts.models import Contract, Clin, Buyer, Nsn, Supplier, ContractType
import csv
from io import StringIO
import random
from datetime import datetime, timedelta
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Count
import decimal

@method_decorator(login_required, name='dispatch')
class ContractQueueListView(ListView):
    model = QueueContract
    template_name = 'processing/contract_queue.html'
    context_object_name = 'queued_contracts'
    
    def get_queryset(self):
        return QueueContract.objects.all().order_by('award_date')

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

@require_http_methods(["POST"])
@login_required
def upload_csv(request):
    """Upload and process a CSV file for contract queue"""
    if 'csv_file' not in request.FILES:
        return JsonResponse({
            'success': False,
            'error': 'No file uploaded',
            'error_type': 'missing_file'
        })
    
    try:
        csv_file = request.FILES['csv_file']
        
        # Validate file type
        if not csv_file.name.endswith('.csv'):
            return JsonResponse({
                'success': False,
                'error': 'Invalid file type. Please upload a CSV file.',
                'error_type': 'invalid_file_type'
            })
        
        try:
            csv_data = csv_file.read().decode('utf-8')
        except UnicodeDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid file encoding. Please ensure the CSV file is saved with UTF-8 encoding.',
                'error_type': 'encoding_error'
            })
            
        csv_reader = csv.DictReader(StringIO(csv_data))
        
        # Validate required columns
        required_columns = [
            'Contract Number', 'Buyer', 'Award Date', 'Due Date', 'Contract Value',
            'Contract Type', 'Solicitation Type', 'Item Number', 'Item Type', 'NSN',
            'NSN Description', 'Order Qty', 'Unit Price'
        ]
        
        missing_columns = [col for col in required_columns if col not in csv_reader.fieldnames]
        if missing_columns:
            return JsonResponse({
                'success': False,
                'error': f'Missing required columns: {", ".join(missing_columns)}',
                'error_type': 'missing_columns',
                'missing_columns': missing_columns
            })
        
        # Define required decimal fields and their validation
        decimal_fields = {
            'Contract Value': 'contract_value',
            'Order Qty': 'order_qty',
            'Item Value': 'item_value',
            'Unit Price': 'unit_price',
            'Supplier Unit Price': 'supplier_unit_price',
            'Supplier Price': 'supplier_price'
        }
        
        # Define date fields for validation
        date_fields = ['Award Date', 'Due Date', 'Supplier Due Date']
        
        with transaction.atomic():
            current_contract = None
            row_number = 0
            
            for row in csv_reader:
                row_number += 1
                
                # Validate required fields
                for field in required_columns:
                    if not row.get(field):
                        return JsonResponse({
                            'success': False,
                            'error': f'Missing required value in row {row_number}, column "{field}"',
                            'error_type': 'missing_value',
                            'row': row_number,
                            'column': field
                        })
                
                # Validate decimal fields
                for field_name, model_field in decimal_fields.items():
                    if field_name in row and row[field_name]:
                        try:
                            value = row[field_name].strip()
                            if value.startswith('$'):  # Handle dollar signs
                                value = value[1:]
                            if value.replace(',', '').replace('.', '').replace('-', '').isdigit():
                                value = value.replace(',', '')  # Remove commas
                                decimal.Decimal(value)
                            else:
                                raise decimal.InvalidOperation(f"Invalid characters in number: {value}")
                        except (decimal.InvalidOperation, ValueError) as e:
                            return JsonResponse({
                                'success': False,
                                'error': f'Invalid decimal value in row {row_number}, column "{field_name}". Please enter a valid number.',
                                'error_type': 'invalid_decimal',
                                'row': row_number,
                                'column': field_name,
                                'value': row[field_name]
                            })
                
                # Validate date fields
                for field in date_fields:
                    if field in row and row[field]:
                        try:
                            datetime.strptime(row[field], '%Y-%m-%d')
                        except ValueError:
                            return JsonResponse({
                                'success': False,
                                'error': f'Invalid date format in row {row_number}, column "{field}". Please use YYYY-MM-DD format.',
                                'error_type': 'invalid_date',
                                'row': row_number,
                                'column': field,
                                'value': row[field]
                            })
                        
                # Validate contract number
                contract_number = row['Contract Number']
                validation_response = validate_contract_number(request, contract_number)
                if not validation_response.get('success'):
                    return validation_response
                
                # If this is a new contract (different contract number)
                if not current_contract or current_contract.contract_number != row['Contract Number']:
                    try:
                        # Create new contract queue entry
                        current_contract = QueueContract.objects.create(
                            contract_number=row['Contract Number'],
                            buyer=row['Buyer'],
                            award_date=datetime.strptime(row['Award Date'], '%Y-%m-%d') if row['Award Date'] else None,
                            due_date=datetime.strptime(row['Due Date'], '%Y-%m-%d') if row['Due Date'] else None,
                            contract_value=decimal.Decimal(row['Contract Value'].replace(',', '').replace('$', '')) if row['Contract Value'] else None,
                            contract_type=row['Contract Type'],
                            solicitation_type=row['Solicitation Type'],
                            created_by=request.user,
                            modified_by=request.user
                        )
                    except Exception as e:
                        return JsonResponse({
                            'success': False,
                            'error': f'Error creating contract in row {row_number}: {str(e)}',
                            'error_type': 'contract_creation_error',
                            'row': row_number,
                            'contract_number': row['Contract Number']
                        })
                
                try:
                    # Handle supplier fields - convert empty strings to None
                    supplier = row['Supplier'].strip() if row['Supplier'] else None
                    supplier_due_date = datetime.strptime(row['Supplier Due Date'], '%Y-%m-%d') if row['Supplier Due Date'] else None
                    supplier_unit_price = decimal.Decimal(row['Supplier Unit Price'].replace(',', '').replace('$', '')) if row['Supplier Unit Price'] else None
                    supplier_price = decimal.Decimal(row['Supplier Price'].replace(',', '').replace('$', '')) if row['Supplier Price'] else None
                    supplier_payment_terms = row['Supplier Payment Terms'].strip() if row['Supplier Payment Terms'] else None
                    
                    # Create CLIN queue entry
                    QueueClin.objects.create(
                        contract_queue=current_contract,
                        item_number=row['Item Number'],
                        item_type=row['Item Type'],
                        nsn=row['NSN'],
                        nsn_description=row['NSN Description'],
                        ia=row['IA'],
                        fob=row['FOB'],
                        due_date=datetime.strptime(row['Due Date'], '%Y-%m-%d') if row['Due Date'] else None,
                        order_qty=decimal.Decimal(row['Order Qty'].replace(',', '')) if row['Order Qty'] else None,
                        item_value=decimal.Decimal(row['Item Value'].replace(',', '').replace('$', '')) if row['Item Value'] else None,
                        unit_price=decimal.Decimal(row['Unit Price'].replace(',', '').replace('$', '')) if row['Unit Price'] else None,
                        supplier=supplier,
                        supplier_due_date=supplier_due_date,
                        supplier_unit_price=supplier_unit_price,
                        supplier_price=supplier_price,
                        supplier_payment_terms=supplier_payment_terms,
                        created_by=request.user,
                        modified_by=request.user
                    )
                except Exception as e:
                    return JsonResponse({
                        'success': False,
                        'error': f'Error creating CLIN in row {row_number}: {str(e)}',
                        'error_type': 'clin_creation_error',
                        'row': row_number,
                        'item_number': row['Item Number']
                    })
        
        return JsonResponse({
            'success': True,
            'message': 'CSV file processed successfully'
        })
    except csv.Error as e:
        return JsonResponse({
            'success': False,
            'error': f'CSV file is malformed: {str(e)}',
            'error_type': 'csv_format_error'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error processing CSV file: {str(e)}',
            'error_type': 'general_error'
        })

@login_required
@require_POST
def cancel_processing(request, queue_id):
    """
    Cancel the processing of a contract and reset its status
    """
    try:
        queue_contract = get_object_or_404(QueueContract, id=queue_id)
        
        # Delete the ProcessContract if it exists
        ProcessContract.objects.filter(queue_contract=queue_contract).delete()
        
        # Reset the queue contract status
        queue_contract.is_being_processed = False
        queue_contract.processed_by = None
        queue_contract.processing_started = None
        queue_contract.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Processing cancelled successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400) 
    

def validate_contract_number(request, contract_number):
    """
    Validates if a contract number already exists in either the Contract or QueueContract tables.
    Returns a JSON response indicating whether the contract number is available.
    """
    try:
        Contract.objects.get(contract_number=contract_number)
        return JsonResponse({
            'success': False,
            'message': f'Contract number "{contract_number}" already exists in the Contract table.'
        })
    except Contract.DoesNotExist:
        try:
            QueueContract.objects.get(contract_number=contract_number)
            return JsonResponse({
                'success': False,
                'message': f'Contract number "{contract_number}" already exists in the QueueContract table.'
            })
        except QueueContract.DoesNotExist:
            return JsonResponse({
                'success': True,
                'message': f'Contract number "{contract_number}" is available.'
            })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'An unexpected error occurred: {str(e)}'
        })

