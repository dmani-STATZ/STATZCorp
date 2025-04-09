from django.shortcuts import render
from django.views.generic import ListView
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.db import transaction
from django.utils import timezone
from ..models import ContractQueue, ClinQueue, SequenceNumber, Contract, Clin, Buyer, Nsn, Supplier, ContractType
import csv
from io import StringIO
import random
from datetime import datetime, timedelta

@method_decorator(login_required, name='dispatch')
class ContractQueueListView(ListView):
    model = ContractQueue
    template_name = 'contracts/contract_queue.html'
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
                if contract_queue.processed_by == request.user:
                    # If the same user is trying to process it again, allow it
                    return JsonResponse({'success': True})
                return JsonResponse({
                    'success': False,
                    'error': 'This contract is already being processed by another user'
                })
            
            contract_queue.is_being_processed = True
            contract_queue.processed_by = request.user
            contract_queue.processing_started = timezone.now()
            contract_queue.save()
            
            return JsonResponse({'success': True})
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
    po_number = request.POST.get('po_number')
    tab_number = request.POST.get('tab_number')
    
    try:
        with transaction.atomic():
            # Get the queued contract
            contract_queue = ContractQueue.objects.select_for_update().get(id=contract_queue_id)
            
            # Verify the user is authorized to process it
            if not contract_queue.is_being_processed:
                return JsonResponse({
                    'success': False,
                    'error': 'This contract must be marked for processing first. Please click the Process button again.'
                })
            
            if contract_queue.processed_by != request.user:
                # If no one is processing it, allow this user to take over
                if contract_queue.processed_by is None:
                    contract_queue.processed_by = request.user
                    contract_queue.save()
                else:
                    return JsonResponse({
                        'success': False,
                        'error': f'This contract is being processed by {contract_queue.processed_by.username}. Please wait until they are finished.'
                    })
            
            # Try to match the buyer
            buyer = None
            if contract_queue.buyer:
                buyer = Buyer.objects.filter(description__iexact=contract_queue.buyer).first()
            
            # Try to match the contract type
            contract_type = None
            if contract_queue.contract_type:
                contract_type = ContractType.objects.filter(description__iexact=contract_queue.contract_type).first()
            
            # Create the live contract
            contract = Contract.objects.create(
                contract_number=contract_queue.contract_number,
                buyer=buyer,
                award_date=contract_queue.award_date,
                due_date=contract_queue.due_date,
                contract_value=contract_queue.contract_value,
                contract_type=contract_type,
                solicitation_type=contract_queue.solicitation_type,
                po_number=po_number,
                tab_num=tab_number,
                created_by=request.user,
                modified_by=request.user
            )
            
            # Process all CLINs
            for clin_queue in contract_queue.clins.all():
                # Try to match NSN
                nsn = None
                if clin_queue.nsn:
                    nsn = Nsn.objects.filter(nsn_code__iexact=clin_queue.nsn).first()
                
                # Try to match supplier
                supplier = None
                if clin_queue.supplier:
                    supplier = Supplier.objects.filter(name__iexact=clin_queue.supplier).first()
                
                # Create the live CLIN
                Clin.objects.create(
                    contract=contract,
                    item_number=clin_queue.item_number,
                    item_type=clin_queue.item_type,
                    nsn=nsn,
                    ia=clin_queue.ia,
                    fob=clin_queue.fob,
                    due_date=clin_queue.due_date,
                    order_qty=clin_queue.order_qty,
                    item_value=clin_queue.item_value,
                    unit_price=clin_queue.unit_price,
                    supplier=supplier,
                    supplier_due_date=clin_queue.supplier_due_date,
                    price_per_unit=clin_queue.supplier_unit_price,
                    quote_value=clin_queue.supplier_price,
                    special_payment_terms=clin_queue.supplier_payment_terms,
                    created_by=request.user,
                    modified_by=request.user
                )
            
            # Delete the queued contract and its CLINs
            contract_queue.delete()
            
            return JsonResponse({'success': True})
            
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
    """Generate and serve a CSV template file for contract queue uploads"""
    # Create a StringIO object to write the CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Write headers
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
    
    # Write example data
    writer.writerow([
        'W52P1J-24-C-0001',  # Contract Number
        'DLA LAND AND MARITIME',  # Buyer
        '2024-01-15',  # Award Date
        '2024-07-15',  # Due Date
        '100000.00',  # Contract Value
        'Unilateral',  # Contract Type
        'SDVOSB',  # Solicitation Type
        '0001',  # Item Number
        'Production',  # Item Type
        '5935-01-123-4567',  # NSN
        'BOLT, MACHINE',  # NSN Description
        'O',  # IA
        'D',  # FOB
        '2024-07-15',  # Due Date
        '100',  # Order Qty
        '5000.00',  # Item Value
        '50.00',  # Unit Price
        'ABC Manufacturing',  # Supplier
        '2024-06-15',  # Supplier Due Date
        '45.00',  # Supplier Unit Price
        '4500.00',  # Supplier Price
        'Net 30'  # Supplier Payment Terms
    ])
    
    # Create the response
    response = HttpResponse(output.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="contract_queue_template.csv"'
    
    return response

def download_test_data(request):
    """Generate and serve a CSV file with random test data"""
    # Create a StringIO object to write the CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Write headers
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
    
    # Get real NSNs and suppliers from the database
    real_nsns = list(Nsn.objects.values_list('nsn_code', 'description')[:50])  # Get first 50 NSNs
    real_suppliers = list(Supplier.objects.values_list('name', flat=True)[:50])  # Get first 50 suppliers
    
    # Generate 5 random contracts with 1-3 CLINs each
    buyers = ['DLA LAND AND MARITIME', 'DLA AVIATION', 'DLA TROOP SUPPORT', 'DLA DISTRIBUTION']
    contract_types = ['Unilateral', 'Bilateral', 'IDIQ', 'Blanket Purchase Agreement']
    solicitation_types = ['SDVOSB', '8(a)', 'Small Business', 'Full and Open']
    item_types = ['Production', 'Service', 'Material', 'Maintenance']
    made_up_suppliers = ['ABC Manufacturing', 'XYZ Services', '123 Industries', 'Best Parts Co']
    payment_terms = ['Net 30', 'Net 45', 'Net 60', '2/10 Net 30']
    
    for contract_num in range(1, 16):
        contract_number = f'W52P1J-24-C-{contract_num:04d}'
        buyer = random.choice(buyers)
        award_date = (datetime.now() - timedelta(days=random.randint(1, 30))).strftime('%Y-%m-%d')
        due_date = (datetime.now() + timedelta(days=random.randint(60, 180))).strftime('%Y-%m-%d')
        contract_type = random.choice(contract_types)
        solicitation_type = random.choice(solicitation_types)
        
        # Generate 1-3 CLINs for each contract
        num_clins = random.randint(1, 3)
        clin_rows = []
        total_contract_value = 0
        
        for clin_num in range(1, num_clins + 1):
            item_number = f'{clin_num:04d}'
            item_type = random.choice(item_types)
            
            # Mix of real and made-up NSNs
            if random.random() < 0.5 and real_nsns:  # 50% chance to use real NSN
                nsn, nsn_desc = random.choice(real_nsns)
            else:
                nsn = f'5935-01-{random.randint(1000000, 9999999)}'
                nsn_desc = f'Test Item {random.randint(1, 100)}'
            
            ia = random.choice(['O', 'D'])
            fob = random.choice(['D', 'O', 'F'])
            clin_due_date = (datetime.now() + timedelta(days=random.randint(30, 150))).strftime('%Y-%m-%d')
            order_qty = random.randint(10, 1000)
            unit_price = round(random.uniform(10, 1000), 2)
            item_value = round(order_qty * unit_price, 2)
            total_contract_value += item_value
            
            # Mix of real and made-up suppliers
            if random.random() < 0.5 and real_suppliers:  # 50% chance to use real supplier
                supplier = random.choice(real_suppliers)
            else:
                supplier = random.choice(made_up_suppliers)
            
            supplier_due_date = (datetime.now() + timedelta(days=random.randint(15, 120))).strftime('%Y-%m-%d')
            supplier_unit_price = round(unit_price * random.uniform(0.8, 0.95), 2)
            supplier_price = round(order_qty * supplier_unit_price, 2)
            supplier_payment_terms = random.choice(payment_terms)
            
            clin_rows.append([
                contract_number,
                buyer,
                award_date,
                due_date,
                total_contract_value,  # This will be updated for each CLIN
                contract_type,
                solicitation_type,
                item_number,
                item_type,
                nsn,
                nsn_desc,
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
        
        # Write all CLINs for this contract
        for row in clin_rows:
            # Update the contract value in each row to be the total
            row[4] = total_contract_value
            writer.writerow(row)
    
    # Create the response
    response = HttpResponse(output.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="contract_test_data.csv"'
    
    return response

@require_http_methods(["POST"])
@login_required
def upload_csv(request):
    """Handle CSV file upload for contract queue"""
    try:
        if 'csv_file' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': 'No file uploaded'
            })
        
        csv_file = request.FILES['csv_file']
        if not csv_file.name.endswith('.csv'):
            return JsonResponse({
                'success': False,
                'error': 'File must be a CSV'
            })
        
        # Read the CSV file
        decoded_file = csv_file.read().decode('utf-8').splitlines()
        reader = csv.DictReader(decoded_file)
        
        # Process each row
        for row in reader:
            # Create or get the contract queue
            contract_queue, created = ContractQueue.objects.get_or_create(
                contract_number=row['Contract Number'],
                defaults={
                    'buyer': row['Buyer'],
                    'award_date': row['Award Date'],
                    'due_date': row['Due Date'],
                    'contract_value': row['Contract Value'],
                    'contract_type': row['Contract Type'],
                    'solicitation_type': row['Solicitation Type'],
                    'created_by': request.user
                }
            )
            
            # Create the CLIN queue
            ClinQueue.objects.create(
                contract_queue=contract_queue,
                item_number=row['Item Number'],
                item_type=row['Item Type'],
                nsn=row['NSN'],
                nsn_description=row['NSN Description'],
                ia=row['IA'],
                fob=row['FOB'],
                due_date=row['Due Date'],
                order_qty=row['Order Qty'],
                item_value=row['Item Value'],
                unit_price=row['Unit Price'],
                supplier=row['Supplier'],
                supplier_due_date=row['Supplier Due Date'],
                supplier_unit_price=row['Supplier Unit Price'],
                supplier_price=row['Supplier Price'],
                supplier_payment_terms=row['Supplier Payment Terms'],
                created_by=request.user
            )
        
        return JsonResponse({
            'success': True,
            'message': 'CSV uploaded successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }) 