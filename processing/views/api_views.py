from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST
from django.shortcuts import get_object_or_404
from django.db import transaction
from ..models import ProcessContract, ProcessClin, SpecialPaymentTerms, ProcessContractSplit
from ..forms import ProcessContractForm, ProcessClinForm
import json
from decimal import Decimal
from django.db.models import Sum

@login_required
@require_http_methods(["GET"])
def get_processing_contract(request, id):
    """Get processing contract details"""
    try:
        process_contract = get_object_or_404(ProcessContract, id=id)
        clins = process_contract.clins.all()
        
        return JsonResponse({
            'success': True,
            'contract': {
                'id': process_contract.id,
                'contract_number': process_contract.contract_number,
                'solicitation_type': process_contract.solicitation_type,
                'po_number': process_contract.po_number,
                'tab_num': process_contract.tab_num,
                'buyer': process_contract.buyer.id if process_contract.buyer else None,
                'buyer_text': process_contract.buyer_text,
                'contract_type': process_contract.contract_type.id if process_contract.contract_type else None,
                'award_date': process_contract.award_date,
                'due_date': process_contract.due_date,
                'contract_value': process_contract.contract_value,
                'description': process_contract.description,
                'status': process_contract.status
            },
            'clins': [{
                'id': clin.id,
                'item_number': clin.item_number,
                'nsn': clin.nsn.id if clin.nsn else None,
                'nsn_text': clin.nsn_text,
                'supplier': clin.supplier.id if clin.supplier else None,
                'supplier_text': clin.supplier_text,
                'order_qty': clin.order_qty,
                'unit_price': clin.unit_price,
                'item_value': clin.item_value,
                'description': clin.description
            } for clin in clins]
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
@require_http_methods(["PUT"])
def update_processing_contract(request, id):
    """Update processing contract details"""
    try:
        data = json.loads(request.body)
        process_contract = get_object_or_404(ProcessContract, id=id)
        
        form = ProcessContractForm(data, instance=process_contract)
        if form.is_valid():
            process_contract = form.save(commit=False)
            process_contract.modified_by = request.user
            process_contract.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Contract updated successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': form.errors
            })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
@require_http_methods(["POST"])
def add_processing_clin(request, id):
    """Add a new CLIN to a processing contract by copying from CLIN 0001"""
    try:
        process_contract = get_object_or_404(ProcessContract, id=id)
        
        # Get the source CLIN (0001)
        source_clin = ProcessClin.objects.filter(
            process_contract=process_contract,
            item_number='0001'
        ).first()
        
        if source_clin:
            # Create new CLIN by copying from source_clin
            source_clin.pk = None  # This will create a new instance
            source_clin.item_number = None  # Clear item number (will be auto-assigned)
            # Reset numeric fields
            source_clin.order_qty = 0
            source_clin.unit_price = 0
            source_clin.item_value = 0
            source_clin.price_per_unit = 0
            source_clin.quote_value = 0
            # Keep special payment terms from source CLIN
            source_clin.save()
            
            return JsonResponse({
                'success': True,
                'clin': {
                    'id': source_clin.id,
                    'item_number': source_clin.item_number
                }
            })
        else:
            # If no source CLIN exists, create a blank one
            new_clin = ProcessClin.objects.create(
                process_contract=process_contract,
                status='draft',
                special_payment_terms=None  # Explicitly set to None
            )
            return JsonResponse({
                'success': True,
                'clin': {
                    'id': new_clin.id,
                    'item_number': new_clin.item_number
                }
            })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
@require_http_methods(["PUT"])
def update_processing_clin(request, id, clin_id):
    """Update a CLIN in a processing contract"""
    try:
        data = json.loads(request.body)
        process_contract = get_object_or_404(ProcessContract, id=id)
        process_clin = get_object_or_404(ProcessClin, id=clin_id, process_contract=process_contract)
        
        form = ProcessClinForm(data, instance=process_clin)
        if form.is_valid():
            clin = form.save()
            
            return JsonResponse({
                'success': True,
                'message': 'CLIN updated successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': form.errors
            })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
@require_http_methods(["DELETE"])
def delete_processing_clin(request, id, clin_id):
    """Delete a CLIN from a processing contract"""
    try:
        process_contract = get_object_or_404(ProcessContract, id=id)
        process_clin = get_object_or_404(ProcessClin, id=clin_id, process_contract=process_contract)
        
        process_clin.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'CLIN deleted successfully'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

def update_process_contract_field(request, pk):
    """
    Updates a single field in the ProcessContract model.
    Expects POST data with:
    - field_name: name of the field to update
    - field_value: new value for the field
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Only POST method allowed'}, status=405)

    field_name = request.POST.get('field_name')
    field_value = request.POST.get('field_value')
    
    if not field_name:
        return JsonResponse({'status': 'error', 'message': 'field_name is required'}, status=400)

    instance = get_object_or_404(ProcessContract, pk=pk)
    
    try:
        if field_name == 'contract_type':
            # Handle contract type selection
            if field_value:
                instance.contract_type_id = field_value
                #instance.contract_type_text = instance.contract_type.description
            else:
                instance.contract_type = None
                #instance.contract_type_text = None
                
        elif field_name == 'sales_class':
            # Handle sales class selection
            if field_value:
                instance.sales_class_id = field_value
                #instance.sales_class_text = instance.sales_class.sales_team
            else:
                instance.sales_class = None
                #instance.sales_class_text = None

        elif field_name == 'buyer':
            # Buyer should only be updated through the match process
            return JsonResponse({
                'status': 'error', 
                'message': 'Buyer must be updated through the match process'
            }, status=400)
            
        elif field_name in ['contract_value', 'plan_gross']:
            # Handle numeric fields
            try:
                setattr(instance, field_name, float(field_value) if field_value else 0.0)
            except ValueError:
                return JsonResponse({
                    'status': 'error',
                    'message': f'{field_name} must be a number'
                }, status=400)
                
        elif field_name in ['award_date', 'due_date']:
            # Handle date fields - assuming date format YYYY-MM-DD
            if not field_value:
                setattr(instance, field_name, None)
            else:
                setattr(instance, field_name, field_value)
                
        elif field_name == 'nist':
            # Handle NIST boolean field
            if field_value.lower() in ['yes', 'true', '1']:
                instance.nist = True
            elif field_value.lower() in ['no', 'false', '0']:
                instance.nist = False
            else:
                return JsonResponse({
                    'status': 'error',
                    'message': 'NIST must be Yes or No'
                }, status=400)
            
        else:
            # Handle regular text fields
            setattr(instance, field_name, field_value if field_value else None)
        
        instance.save()
        
        # Return the new value and any related field values
        response_data = {
            'status': 'success',
            'field_name': field_name,
            'field_value': field_value,
            'related_updates': {}
        }
        
        # Add related field updates to response
        if field_name == 'contract_type':
            response_data['related_updates']['contract_type_text'] = instance.contract_type_text
        elif field_name == 'sales_class':
            response_data['related_updates']['sales_class_text'] = instance.sales_class_text
        elif field_name == 'nist':
            # Return the display value for NIST
            response_data['field_value'] = 'Yes' if instance.nist else 'No'
            
        return JsonResponse(response_data)
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error updating {field_name}: {str(e)}'
        }, status=500)

@login_required
@require_http_methods(["POST"])
def update_clin_field(request, pk, clin_id):
    """
    Updates a single field in a ProcessClin model.
    Expects POST data with:
    - field_name: name of the field to update
    - field_value: new value for the field
    """
    field_name = request.POST.get('field_name')
    field_value = request.POST.get('field_value')
    
    if not field_name:
        return JsonResponse({'status': 'error', 'message': 'field_name is required'}, status=400)

    process_contract = get_object_or_404(ProcessContract, pk=pk)
    clin = get_object_or_404(ProcessClin, id=clin_id, process_contract=process_contract)
    
    try:
        # Protect fields that should only be updated through match process
        protected_fields = ['nsn', 'nsn_text', 'nsn_description_text', 'supplier', 'supplier_text']
        if field_name in protected_fields:
            return JsonResponse({
                'status': 'error', 
                'message': f'{field_name} must be updated through the match process'
            }, status=400)
            
        elif field_name in ['order_qty', 'unit_price', 'price_per_unit']:
            # Handle numeric fields
            try:
                # Convert order_qty to float since it's stored as FloatField
                if field_name == 'order_qty':
                    value = float(field_value) if field_value else 0.0
                # Convert price fields to Decimal since they're stored as DecimalField
                else:
                    value = Decimal(field_value) if field_value else Decimal('0.0')
                
                setattr(clin, field_name, value)
                
                # Recalculate dependent values
                if field_name in ['order_qty', 'unit_price']:
                    # Convert to Decimal for calculation
                    qty = Decimal(str(clin.order_qty))
                    price = clin.unit_price if isinstance(clin.unit_price, Decimal) else Decimal(str(clin.unit_price))
                    clin.item_value = qty * price
                    
                if field_name in ['order_qty', 'price_per_unit']:
                    # Convert to Decimal for calculation
                    qty = Decimal(str(clin.order_qty))
                    price = clin.price_per_unit if isinstance(clin.price_per_unit, Decimal) else Decimal(str(clin.price_per_unit))
                    clin.quote_value = qty * price
                    
            except (ValueError, TypeError) as e:
                return JsonResponse({
                    'status': 'error',
                    'message': f'{field_name} must be a valid number'
                }, status=400)
                
        elif field_name in ['due_date', 'supplier_due_date']:
            # Handle date fields
            if not field_value:
                setattr(clin, field_name, None)
            else:
                setattr(clin, field_name, field_value)
                
        elif field_name == 'item_type':
            # Validate item type choices
            valid_types = [choice[0] for choice in ProcessClin.ITEM_TYPE_CHOICES]
            if field_value not in valid_types:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Invalid item type. Must be one of: {", ".join(valid_types)}'
                }, status=400)
            setattr(clin, field_name, field_value)

                
        elif field_name == 'special_payment_terms':
            # Handle special payment terms selection
            if field_value:
                try:
                    # Try to get the SpecialPaymentTerms instance
                    special_terms = SpecialPaymentTerms.objects.get(code=field_value)
                    clin.special_payment_terms = special_terms
                except SpecialPaymentTerms.DoesNotExist:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Invalid special payment terms code: {field_value}'
                    }, status=400)
            else:
                clin.special_payment_terms = None

        # Handle text fields that don't need special processing
        elif field_name in ['clin_po_num', 'tab_num', 'item_number', 'nsn_text', 'supplier_text', 'uom', 'fob', 'ia']:
            print(f"Saving {field_name} with value: {field_value}")  # Debug log
            setattr(clin, field_name, field_value if field_value else None)
            
            # If this is a supplier or NSN text field, also clear the related object
            if field_name == 'supplier_text':
                clin.supplier = None
            elif field_name == 'nsn_text':
                clin.nsn = None

        clin.save()
        
        # Return the new value and any calculated values
        response_data = {
            'status': 'success',
            'field_name': field_name,
            'field_value': field_value,
            'related_updates': {}
        }
        
        # Add related field updates to response
        if field_name in ['order_qty', 'unit_price']:
            response_data['related_updates']['item_value'] = str(clin.item_value)
        if field_name in ['order_qty', 'price_per_unit']:
            response_data['related_updates']['quote_value'] = str(clin.quote_value)
            
        return JsonResponse(response_data)
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error updating {field_name}: {str(e)}'
        }, status=500)

@login_required
@require_POST
def save_clin(request, clin_id):
    """
    Save CLIN details via AJAX request.
    """
    try:
        clin = get_object_or_404(ProcessClin, id=clin_id)
        
        # Update CLIN fields from form data
        fields_to_update = [
            'item_number', 'item_type', 'clin_po_num', 'tab_num',
            'order_qty', 'uom', 'unit_price', 'item_value',
            'price_per_unit', 'quote_value',
            'due_date', 'supplier_due_date', 'fob', 'ia'
        ]
        
        with transaction.atomic():
            # Handle special payment terms separately
            special_terms_code = request.POST.get('special_payment_terms')
            if special_terms_code:
                try:
                    special_terms = SpecialPaymentTerms.objects.get(code=special_terms_code)
                    clin.special_payment_terms = special_terms
                except SpecialPaymentTerms.DoesNotExist:
                    clin.special_payment_terms = None
            else:
                clin.special_payment_terms = None
            
            # Handle other fields
            for field in fields_to_update:
                if field in request.POST:
                    value = request.POST.get(field)
                    
                    # Handle numeric fields
                    if field in ['order_qty', 'unit_price', 'price_per_unit', 'item_value', 'quote_value']:
                        try:
                            value = Decimal(value) if value else Decimal('0')
                        except (ValueError, TypeError):
                            return JsonResponse({
                                'success': False,
                                'error': f'{field} must be a valid number'
                            }, status=400)
                    
                    # Handle date fields
                    elif field in ['due_date', 'supplier_due_date']:
                        if not value:
                            value = None
                    
                    setattr(clin, field, value)
            
            # Recalculate totals
            if 'order_qty' in request.POST or 'unit_price' in request.POST:
                clin.item_value = Decimal(str(clin.order_qty)) * clin.unit_price
            
            if 'order_qty' in request.POST or 'price_per_unit' in request.POST:
                clin.quote_value = Decimal(str(clin.order_qty)) * clin.price_per_unit
            
            clin.save()
        
        return JsonResponse({
            'success': True,
            'message': 'CLIN details saved successfully',
            'data': {
                'item_value': str(clin.item_value),
                'quote_value': str(clin.quote_value)
            }
        })
        
    except ProcessClin.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'CLIN not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@login_required
@require_POST
def update_contract_values(request, id):
    """Update contract value, plan gross, and handle splits for a process contract"""
    try:
        with transaction.atomic():
            process_contract = get_object_or_404(ProcessContract, id=id)
            
            # Calculate new values
            new_contract_value = process_contract.calculate_contract_value()
            new_plan_gross = process_contract.calculate_plan_gross()
            
            if new_contract_value is None or new_plan_gross is None:
                return JsonResponse({
                    'success': False,
                    'error': 'Failed to calculate contract values'
                }, status=400)
            
            # Get old values for comparison
            old_contract_value = process_contract.contract_value or Decimal('0.00')
            old_plan_gross = process_contract.plan_gross or Decimal('0.00')
            
            # Update contract values
            process_contract.contract_value = new_contract_value
            process_contract.plan_gross = new_plan_gross
            process_contract.save()
            
            # Handle splits if there's a difference
            if old_contract_value != new_contract_value or old_plan_gross != new_plan_gross:
                # Get total of existing splits
                total_split = ProcessContractSplit.objects.filter(
                    process_contract=process_contract
                ).aggregate(split_value=Sum('split_value'))
                
                # Convert total_split to Decimal, default to 0 if None
                current_total_splits = Decimal(str(total_split['split_value'] or '0.00'))
                
                # Calculate the difference between plan_gross and total splits
                split_difference = new_plan_gross - current_total_splits
                
                # Only create a new split if there's a significant difference
                # Using abs() to check if difference is greater than 0.01
                if abs(split_difference) > Decimal('0.01'):
                    split = ProcessContractSplit.objects.create(
                        process_contract=process_contract,
                        company_name='Calculation Difference',
                        split_value=split_difference,  # This can be positive or negative
                    )

            return JsonResponse({
                'success': True,
                'message': 'Contract values updated successfully',
                'data': {
                    'contract_value': str(new_contract_value),
                    'plan_gross': str(new_plan_gross)
                }
            })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)