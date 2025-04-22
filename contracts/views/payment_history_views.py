from django.http import JsonResponse
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Sum
from django.views.decorators.http import require_http_methods
import json

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, Clin, PaymentHistory

@conditional_login_required
@require_http_methods(["GET", "POST"])
def payment_history_api(request, entity_type, entity_id, payment_type):
    """
    API endpoint for managing payment history for both Contracts and CLINs.
    
    Args:
        entity_type: Either 'contract' or 'clin'
        entity_id: The ID of the contract or CLIN
        payment_type: The type of payment being recorded
    """
    # Get the appropriate model and content type
    model_map = {
        'contract': Contract,
        'clin': Clin
    }
    
    if entity_type not in model_map:
        return JsonResponse({'error': f'Invalid entity type: {entity_type}'}, status=400)
    
    model = model_map[entity_type]
    content_type = ContentType.objects.get_for_model(model)
    
    # Get the entity
    try:
        entity = get_object_or_404(model, id=entity_id)
    except model.DoesNotExist:
        return JsonResponse({'error': f'{entity_type.title()} not found'}, status=404)

    if request.method == 'GET':
        # Get payment history entries
        history = PaymentHistory.objects.filter(
            content_type=content_type,
            object_id=entity_id,
            payment_type=payment_type
        ).order_by('-payment_date', '-created_on')
        
        # Calculate total
        total = history.aggregate(total=Sum('payment_amount'))['total'] or 0
        
        # Format response data
        history_data = [{
            'payment_date': entry.payment_date.isoformat(),
            'payment_amount': float(entry.payment_amount),
            'payment_info': entry.payment_info,
            'reference_number': entry.reference_number,
            'created_by': entry.created_by.get_full_name() if entry.created_by else 'System',
            'created_on': entry.created_on.isoformat()
        } for entry in history]
        
        return JsonResponse({
            'success': True,
            'history': history_data,
            'total': float(total),
            'entity_type': entity_type,
            'entity_id': entity_id
        })
    
    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Validate payment type
            valid_types = (PaymentHistory.get_contract_payment_types() 
                         if entity_type == 'contract' 
                         else PaymentHistory.get_clin_payment_types())
            
            if payment_type not in valid_types:
                return JsonResponse({
                    'error': f'Invalid payment type {payment_type} for {entity_type}'
                }, status=400)
            
            # Create new payment history entry
            payment = PaymentHistory.objects.create(
                content_type=content_type,
                object_id=entity_id,
                payment_type=payment_type,
                payment_amount=data['payment_amount'],
                payment_date=data['payment_date'],
                payment_info=data.get('payment_info', ''),
                reference_number=data.get('reference_number', ''),
                created_by=request.user,
                modified_by=request.user
            )
            
            # Calculate new total
            new_total = PaymentHistory.objects.filter(
                content_type=content_type,
                object_id=entity_id,
                payment_type=payment_type
            ).aggregate(total=Sum('payment_amount'))['total'] or 0

        # Update the contract or CLIN total
            if entity_type == 'contract':
                try:
                    contract = Contract.objects.get(id=entity_id)
                    if payment_type == 'contract_value':
                        contract.contract_value = new_total
                    elif payment_type == 'plan_gross':
                        contract.plan_gross = new_total
                    contract.save()
                except Contract.DoesNotExist:
                    print(f"Contract with id {entity_id} not found.")  # Consider more robust error handling

            elif entity_type == 'clin':
                try:
                    clin = Clin.objects.get(id=entity_id)
                    if payment_type == 'item_value':
                        clin.item_value = new_total
                    elif payment_type == 'quote_value':
                        clin.quote_value = new_total
                    elif payment_type == 'paid_amount':
                        clin.paid_amount = new_total
                    elif payment_type == 'wawf_payment':
                        clin.wawf_payment = new_total
                    clin.save()
                except Clin.DoesNotExist:
                    print(f"Clin with id {entity_id} not found.")  # Consider more robust error handling
            
            return JsonResponse({
                'success': True,
                'new_total': float(new_total),
                'payment_id': payment.id,
                'message': 'Payment history entry created successfully'
            })
            
        except (json.JSONDecodeError, KeyError) as e:
            return JsonResponse({
                'error': f'Invalid request data: {str(e)}'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'error': f'Failed to create payment history: {str(e)}'
            }, status=500)

@conditional_login_required
def get_entity_details(request, entity_type, entity_id):
    """Get details about an entity for the payment history popup"""
    model_map = {
        'contract': Contract,
        'clin': Clin
    }
    
    if entity_type not in model_map:
        return JsonResponse({'error': f'Invalid entity type: {entity_type}'}, status=400)
    
    model = model_map[entity_type]
    
    try:
        entity = get_object_or_404(model, id=entity_id)
        
        # Get entity-specific details
        if entity_type == 'contract':
            details = {
                'number': entity.contract_number,
                'valid_payment_types': PaymentHistory.get_contract_payment_types()
            }
        else:  # CLIN
            details = {
                'number': f"CLIN {entity.item_number}",
                'contract_number': entity.contract.contract_number if entity.contract else None,
                'valid_payment_types': PaymentHistory.get_clin_payment_types()
            }
        
        return JsonResponse({
            'success': True,
            'entity_type': entity_type,
            'entity_id': entity_id,
            'details': details
        })
        
    except model.DoesNotExist:
        return JsonResponse({
            'error': f'{entity_type.title()} not found'
        }, status=404) 