from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.db import transaction
from django.utils import timezone
from ..models import QueueContract, QueueClin, SequenceNumber, ProcessContract
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
        return QueueContract.objects.all().order_by('-created_on')

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