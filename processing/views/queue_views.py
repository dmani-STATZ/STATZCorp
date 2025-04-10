from django.shortcuts import render
from django.views.generic import ListView
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.db import transaction
from django.utils import timezone
from ..models import ContractQueue, ClinQueue, SequenceNumber
from contracts.models import Contract, Clin, Buyer, Nsn, Supplier, ContractType
import csv
from io import StringIO
import random
from datetime import datetime, timedelta

@method_decorator(login_required, name='dispatch')
class ContractQueueListView(ListView):
    model = ContractQueue
    template_name = 'processing/contract_queue.html'
    context_object_name = 'queued_contracts'
    
    def get_queryset(self):
        return ContractQueue.objects.all().order_by('-created_on')

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
def start_processing(request):
    """Mark a contract as being processed by a user"""
    contract_queue_id = request.POST.get('contract_queue_id')
    
    try:
        with transaction.atomic():
            contract_queue = ContractQueue.objects.select_for_update().get(id=contract_queue_id)
            
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
    except ContractQueue.DoesNotExist:
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
            contract_queue = ContractQueue.objects.select_for_update().get(id=contract_queue_id)
            
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
    except ContractQueue.DoesNotExist:
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
    
    # Generate some random test data
    for i in range(5):
        contract_number = f"TEST{i+1}"
        buyer = f"Test Buyer {i+1}"
        award_date = (datetime.now() - timedelta(days=random.randint(1, 30))).strftime('%Y-%m-%d')
        due_date = (datetime.now() + timedelta(days=random.randint(30, 90))).strftime('%Y-%m-%d')
        contract_value = round(random.uniform(10000, 100000), 2)
        contract_type = random.choice(['Unilateral', 'Bilateral', 'IDIQ'])
        solicitation_type = 'SDVOSB'
        
        # Generate 1-3 CLINs per contract
        for j in range(random.randint(1, 3)):
            item_number = f"{j+1:04d}"
            item_type = random.choice(['FAT', 'PVT', 'Production'])
            nsn = f"TEST{i+1}{j+1}"
            nsn_description = f"Test NSN Description {i+1}{j+1}"
            ia = random.choice(['O', 'D'])
            fob = random.choice(['O', 'D'])
            clin_due_date = (datetime.now() + timedelta(days=random.randint(30, 90))).strftime('%Y-%m-%d')
            order_qty = random.randint(1, 100)
            item_value = round(random.uniform(1000, 10000), 2)
            unit_price = round(item_value / order_qty, 2)
            supplier = f"Test Supplier {i+1}{j+1}"
            supplier_due_date = (datetime.now() + timedelta(days=random.randint(15, 45))).strftime('%Y-%m-%d')
            supplier_unit_price = round(unit_price * random.uniform(0.8, 1.2), 2)
            supplier_price = round(supplier_unit_price * order_qty, 2)
            supplier_payment_terms = random.choice(['Net 30', 'Net 45', 'Net 60'])
            
            writer.writerow([
                contract_number,
                buyer,
                award_date,
                due_date,
                contract_value,
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
    
    return response

@require_http_methods(["POST"])
@login_required
def upload_csv(request):
    """Upload and process a CSV file for contract queue"""
    if 'csv_file' not in request.FILES:
        return JsonResponse({
            'success': False,
            'error': 'No file uploaded'
        })
    
    try:
        csv_file = request.FILES['csv_file']
        csv_data = csv_file.read().decode('utf-8')
        csv_reader = csv.DictReader(StringIO(csv_data))
        
        with transaction.atomic():
            current_contract = None
            for row in csv_reader:
                # If this is a new contract (different contract number)
                if not current_contract or current_contract.contract_number != row['Contract Number']:
                    # Create new contract queue entry
                    current_contract = ContractQueue.objects.create(
                        contract_number=row['Contract Number'],
                        buyer=row['Buyer'],
                        award_date=datetime.strptime(row['Award Date'], '%Y-%m-%d') if row['Award Date'] else None,
                        due_date=datetime.strptime(row['Due Date'], '%Y-%m-%d') if row['Due Date'] else None,
                        contract_value=row['Contract Value'],
                        contract_type=row['Contract Type'],
                        solicitation_type=row['Solicitation Type'],
                        created_by=request.user,
                        modified_by=request.user
                    )
                
                # Create CLIN queue entry
                ClinQueue.objects.create(
                    contract_queue=current_contract,
                    item_number=row['Item Number'],
                    item_type=row['Item Type'],
                    nsn=row['NSN'],
                    nsn_description=row['NSN Description'],
                    ia=row['IA'],
                    fob=row['FOB'],
                    due_date=datetime.strptime(row['Due Date'], '%Y-%m-%d') if row['Due Date'] else None,
                    order_qty=row['Order Qty'],
                    item_value=row['Item Value'],
                    unit_price=row['Unit Price'],
                    supplier=row['Supplier'],
                    supplier_due_date=datetime.strptime(row['Supplier Due Date'], '%Y-%m-%d') if row['Supplier Due Date'] else None,
                    supplier_unit_price=row['Supplier Unit Price'],
                    supplier_price=row['Supplier Price'],
                    supplier_payment_terms=row['Supplier Payment Terms'],
                    created_by=request.user,
                    modified_by=request.user
                )
        
        return JsonResponse({
            'success': True,
            'message': 'CSV file processed successfully'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }) 