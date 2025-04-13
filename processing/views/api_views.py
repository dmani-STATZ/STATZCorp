from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404
from django.db import transaction
from ..models import ProcessContract, ProcessClin
from ..forms import ProcessContractForm, ProcessClinForm
import json

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
    """Add a new CLIN to a processing contract"""
    try:
        data = json.loads(request.body)
        process_contract = get_object_or_404(ProcessContract, id=id)
        
        form = ProcessClinForm(data)
        if form.is_valid():
            clin = form.save(commit=False)
            clin.process_contract = process_contract
            clin.save()
            
            return JsonResponse({
                'success': True,
                'clin': {
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
                }
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
                instance.contract_type_text = instance.contract_type.description
            else:
                instance.contract_type = None
                instance.contract_type_text = None
                
        elif field_name == 'sales_class':
            # Handle sales class selection
            if field_value:
                instance.sales_class_id = field_value
                instance.sales_class_text = instance.sales_class.sales_team
            else:
                instance.sales_class = None
                instance.sales_class_text = None
                
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
                value = float(field_value) if field_value else 0.0
                setattr(clin, field_name, value)
                
                # Recalculate dependent values
                if field_name in ['order_qty', 'unit_price']:
                    clin.item_value = clin.order_qty * clin.unit_price
                if field_name in ['order_qty', 'price_per_unit']:
                    clin.quote_value = clin.order_qty * clin.price_per_unit
                    
            except ValueError:
                return JsonResponse({
                    'status': 'error',
                    'message': f'{field_name} must be a number'
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
            
        else:
            # Handle regular text fields
            setattr(clin, field_name, field_value if field_value else None)
        
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