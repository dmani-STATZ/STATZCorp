import json

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from contracts.models import Buyer
from processing.models import ProcessClin, ProcessContract
from products.models import Nsn
from suppliers.models import Supplier

def match_buyer(request, pk):
    process_contract = get_object_or_404(ProcessContract, id=pk)
    buyer_text = request.POST.get('buyer_text', '')
    
    # Search for matching buyer
    buyers = Buyer.objects.filter(name__icontains=buyer_text)
    
    if buyers.exists():
        return JsonResponse({
            'success': True,
            'buyers': [{'id': b.id, 'name': b.name} for b in buyers]
        })
    return JsonResponse({'success': False, 'message': 'No matching buyers found'})

def match_nsn(request, pk, clin_id):
    process_clin = get_object_or_404(ProcessClin, id=clin_id)
    nsn_text = request.POST.get('nsn_text', '')
    
    # Search for matching NSN
    nsns = Nsn.objects.filter(nsn__icontains=nsn_text)
    
    if nsns.exists():
        return JsonResponse({
            'success': True,
            'nsns': [{'id': n.id, 'nsn': n.nsn, 'description': n.description} for n in nsns]
        })
    return JsonResponse({'success': False, 'message': 'No matching NSNs found'})

def match_supplier(request, pk, clin_id):
    process_clin = get_object_or_404(ProcessClin, id=clin_id)
    supplier_text = request.POST.get('supplier_text', '')
    
    # Search for matching supplier
    suppliers = Supplier.objects.filter(name__icontains=supplier_text, archived=False)
    
    if suppliers.exists():
        return JsonResponse({
            'success': True,
            'suppliers': [{'id': s.id, 'name': s.name} for s in suppliers]
        })
    return JsonResponse({'success': False, 'message': 'No matching suppliers found'})


def _truthy_json(val):
    if val is True:
        return True
    if val is False or val is None:
        return False
    if isinstance(val, str):
        return val.strip().lower() in ('true', '1', 'yes', 'on')
    return False


@login_required
@require_http_methods(["GET", "POST"])
def match_packhouse(request, process_contract_id):
    """
    Assign, clear, or search packhouse suppliers for a ProcessContract (contract-level).
    GET ?action=search&q=...&prefer_packhouse=1
    POST JSON: {action: 'match', supplier_id}, {action: 'create', name, cage_code, is_packhouse?}, {action: 'clear'}
    clear: nulls packhouse FK, packhouse_quote_amount, and packhouse_notes; recomputes plan_gross via calculate_plan_gross (surgical save).
    """
    process_contract = get_object_or_404(ProcessContract, id=process_contract_id)

    if request.method == 'GET':
        action = request.GET.get('action')
        if action != 'search':
            return JsonResponse({'error': 'Invalid action'}, status=400)
        q = request.GET.get('q', '').strip()
        if len(q) < 3:
            return JsonResponse({'results': []})
        prefer_raw = (request.GET.get('prefer_packhouse') or '').strip().lower()
        prefer_packhouse = prefer_raw in ('1', 'true', 'yes', 'on')
        qs = Supplier.objects.filter(Q(name__icontains=q) | Q(cage_code__icontains=q))
        if prefer_packhouse:
            qs = qs.order_by('-is_packhouse', 'name')
        else:
            qs = qs.order_by('name')
        results = []
        for s in qs[:20]:
            results.append({
                'id': s.id,
                'name': s.name or '',
                'cage_code': s.cage_code or '',
                'is_packhouse': bool(s.is_packhouse),
            })
        return JsonResponse({'results': results})

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)

    action = data.get('action')

    if action == 'clear':
        process_contract.packhouse = None
        process_contract.packhouse_quote_amount = None
        process_contract.packhouse_notes = None
        # Recompute plan_gross now that the packaging deduction is gone.
        # calculate_plan_gross treats null packhouse_quote_amount as zero,
        # so this naturally restores the pre-packaging plan_gross value.
        process_contract.plan_gross = process_contract.calculate_plan_gross()
        process_contract.save(
            update_fields=[
                'packhouse',
                'packhouse_quote_amount',
                'packhouse_notes',
                'plan_gross',
            ]
        )
        return JsonResponse({
            'success': True,
            'cleared': True,
            'plan_gross': (
                str(process_contract.plan_gross)
                if process_contract.plan_gross is not None
                else None
            ),
        })

    if action == 'create':
        name = (data.get('name') or '').strip()
        cage_code = (data.get('cage_code') or data.get('cage') or '').strip()
        if not name:
            return JsonResponse({'success': False, 'error': 'Supplier name required'}, status=400)
        if not cage_code:
            return JsonResponse({'success': False, 'error': 'CAGE code required'}, status=400)
        create_kwargs = {
            'name': name,
            'cage_code': cage_code,
            'created_by': request.user,
            'modified_by': request.user,
        }
        if 'is_packhouse' in data:
            create_kwargs['is_packhouse'] = _truthy_json(data.get('is_packhouse'))
        supplier = Supplier.objects.create(**create_kwargs)
        process_contract.packhouse = supplier
        process_contract.save(update_fields=['packhouse', 'modified_at'])
        process_contract.refresh_from_db()
        return JsonResponse({
            'success': True,
            'packhouse_id': supplier.id,
            'packhouse_name': supplier.name,
            'packhouse_cage': supplier.cage_code or '',
            'is_packhouse': bool(supplier.is_packhouse),
            'plan_gross': (
                str(process_contract.plan_gross)
                if process_contract.plan_gross is not None
                else None
            ),
        })

    if action == 'match':
        supplier_id = data.get('supplier_id') or data.get('id')
        if not supplier_id:
            return JsonResponse({'error': 'No supplier ID provided'}, status=400)
        supplier = get_object_or_404(Supplier, id=supplier_id)
        process_contract.packhouse = supplier
        process_contract.save(update_fields=['packhouse', 'modified_at'])
        process_contract.refresh_from_db()
        return JsonResponse({
            'success': True,
            'packhouse_id': supplier.id,
            'packhouse_name': supplier.name,
            'packhouse_cage': supplier.cage_code or '',
            'is_packhouse': bool(supplier.is_packhouse),
            'plan_gross': (
                str(process_contract.plan_gross)
                if process_contract.plan_gross is not None
                else None
            ),
        })

    return JsonResponse({'error': 'Invalid action'}, status=400)
