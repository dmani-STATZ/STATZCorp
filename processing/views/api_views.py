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