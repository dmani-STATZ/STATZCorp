import json
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods

from STATZWeb.decorators import conditional_login_required

from ..models import Clin, ClinSplit


def _parse_decimal(val):
    if val is None or val == '':
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return None


@conditional_login_required
@require_http_methods(['POST'])
def add_clin_split(request, clin_pk):
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)

    clin = get_object_or_404(Clin.objects.filter(company=company), pk=clin_pk)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    company_name = (data.get('company_name') or '').strip()
    if not company_name:
        return JsonResponse({'success': False, 'error': 'Company name is required'}, status=400)

    split_value = _parse_decimal(data.get('split_value'))
    split_paid = _parse_decimal(data.get('split_paid'))

    row = ClinSplit.objects.create(
        clin=clin,
        company_name=company_name,
        split_value=split_value,
        split_paid=split_paid,
    )

    return JsonResponse({
        'success': True,
        'split_id': row.id,
        'company_name': row.company_name,
        'split_value': str(row.split_value) if row.split_value is not None else None,
        'split_paid': str(row.split_paid) if row.split_paid is not None else None,
    })


@conditional_login_required
@require_http_methods(['POST'])
def update_clin_split(request, split_pk):
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)

    split = get_object_or_404(
        ClinSplit.objects.select_related('clin').filter(clin__company=company),
        pk=split_pk,
    )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    if 'company_name' in data:
        cn = (data.get('company_name') or '').strip()
        if not cn:
            return JsonResponse({'success': False, 'error': 'Company name is required'}, status=400)
        split.company_name = cn
    if 'split_value' in data:
        split.split_value = _parse_decimal(data.get('split_value'))
    if 'split_paid' in data:
        split.split_paid = _parse_decimal(data.get('split_paid'))

    split.save()

    return JsonResponse({'success': True})


@conditional_login_required
@require_http_methods(['POST'])
def delete_clin_split(request, split_pk):
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)

    split = get_object_or_404(
        ClinSplit.objects.filter(clin__company=company),
        pk=split_pk,
    )
    split.delete()
    return JsonResponse({'success': True})


@conditional_login_required
@require_GET
def get_clin_splits(request, clin_pk):
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'error': 'No active company'}, status=403)

    clin = get_object_or_404(Clin.objects.filter(company=company), pk=clin_pk)
    rows = [
        {
            'id': s.id,
            'company_name': s.company_name,
            'split_value': str(s.split_value) if s.split_value is not None else None,
            'split_paid': str(s.split_paid) if s.split_paid is not None else None,
        }
        for s in clin.splits.all()
    ]
    return JsonResponse(rows, safe=False)
