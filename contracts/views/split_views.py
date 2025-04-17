import json
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from ..models import ContractSplit

@require_http_methods(["POST"])
def create_split_view(request):
    try:
        data = json.loads(request.body)
        split = ContractSplit.create_split(
            contract_id=data['contract_id'],
            company_name=data['company_name'],
            split_value=data['split_value'],
            split_paid=data['split_paid']
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
        split = ContractSplit.update_split(
            contract_split_id=split_id,
            company_name=data.get('company_name'),
            split_value=data.get('split_value'),
            split_paid=data.get('split_paid')
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
def delete_split_view(request, split_id):
    try:
        success = ContractSplit.delete_split(split_id)
        return JsonResponse({'success': success})
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)
