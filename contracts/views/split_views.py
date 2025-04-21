import json
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404
from ..models import Contract, ContractSplit

@require_http_methods(["POST"])
def create_split(request):
    """Create a new contract split."""
    try:
        data = json.loads(request.body)
        contract = get_object_or_404(Contract, id=data.get('contract_id'))
        
        # Create new split
        split = ContractSplit.objects.create(
            contract=contract,
            company_name=data.get('company_name'),
            split_value=data.get('split_value', 0.00),
            split_paid=data.get('split_paid', 0.00)
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
def update_split(request, split_id):
    """Update an existing contract split."""
    try:
        data = json.loads(request.body)
        split = get_object_or_404(ContractSplit, id=split_id)
        
        # Update split fields
        split.company_name = data.get('company_name', split.company_name)
        split.split_value = data.get('split_value', split.split_value)
        split.split_paid = data.get('split_paid', split.split_paid)
        split.save()
        
        return JsonResponse({
            'success': True
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@require_http_methods(["POST"])
def delete_split(request, split_id):
    """Delete a contract split."""
    try:
        split = get_object_or_404(ContractSplit, id=split_id)
        split.delete()
        
        return JsonResponse({
            'success': True
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

# Optional: View for loading splits via AJAX
@require_http_methods(["GET"])
def get_contract_splits(request, contract_id):
    """Get HTML for contract splits section."""
    from django.template.loader import render_to_string
    
    contract = get_object_or_404(Contract, id=contract_id)
    html = render_to_string('contracts/partials/contract_splits.html', {
        'contract': contract,
        'mode': request.GET.get('mode', 'detail')
    })
    
    return JsonResponse({
        'success': True,
        'html': html
    })
