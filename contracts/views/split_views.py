import json
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods

from STATZWeb.decorators import conditional_login_required

from ..models import Clin, ClinSplit
from contracts.models import ContractPackaging
from collections import defaultdict



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
    percentage = _parse_decimal(data.get('percentage'))

    row = ClinSplit.objects.create(
        clin=clin,
        company_name=company_name,
        split_value=split_value,
        split_paid=split_paid,
        percentage=percentage,
    )

    return JsonResponse({
        'success': True,
        'split_id': row.id,
        'company_name': row.company_name,
        'split_value': str(row.split_value) if row.split_value is not None else None,
        'split_paid': str(row.split_paid) if row.split_paid is not None else None,
        'percentage': str(row.percentage) if row.percentage is not None else None,
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
    if 'percentage' in data:
        split.percentage = _parse_decimal(data.get('percentage'))

    apply_to_all = bool(data.get('apply_to_all_clins', False))

    split.save()

    if apply_to_all and 'percentage' in data:
        new_pct = split.percentage
        contract = split.clin.contract
        # Intentional bulk update: percentage propagation is not an audited financial field.
        ClinSplit.objects.filter(
            clin__contract=contract,
            company_name__iexact=split.company_name,
        ).exclude(pk=split.pk).update(percentage=new_pct)

    return JsonResponse({'success': True, 'applied_to_all': apply_to_all})


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
            'percentage': str(s.percentage) if s.percentage is not None else None,
        }
        for s in clin.splits.all()
    ]
    return JsonResponse(rows, safe=False)


@conditional_login_required
@require_http_methods(['POST'])
def recalc_splits(request, contract_pk):
    from ..models import Contract, Clin

    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)

    contract = get_object_or_404(Contract.objects.filter(company=company), pk=contract_pk)

    # Step 1: Load all CLINs with prefetch to avoid N+1
    clins = list(
        Clin.objects.filter(contract=contract).prefetch_related(
            Prefetch('splits', queryset=ClinSplit.objects.all()),
            'finance_lines',
        )
    )

    # Step 2: Compute sum of all CLIN adj_gross values inline
    # (same pattern as existing code  avoids property N+1)
    total_clin_adj_gross = Decimal('0.00')
    for clin in clins:
        item_val = Decimal(str(clin.item_value or 0))
        quote_val = Decimal(str(clin.quote_value or 0))
        paid_val = Decimal(str(clin.paid_amount or 0))
        cost = paid_val if paid_val != Decimal('0') else quote_val
        gross = item_val - cost
        finance_costs = sum(
            Decimal(str(fl.amount_billed or 0))
            for fl in clin.finance_lines.all()
        )
        total_clin_adj_gross += gross - finance_costs

    # Step 3: Packaging deduction (same COALESCE logic as Contract.adjusted_gross property)
    packaging_deduction = Decimal('0.00')
    try:
        pkg = contract.packaging
        if pkg.amount_paid is not None and Decimal(str(pkg.amount_paid)) != Decimal('0'):
            packaging_deduction = Decimal(str(pkg.amount_paid))
        elif pkg.quote_amount is not None and Decimal(str(pkg.quote_amount)) != Decimal('0'):
            packaging_deduction = Decimal(str(pkg.quote_amount))
    except Exception:
        pass

    # Step 4: Contract-level charges deduction (same COALESCE logic)
    charges_deduction = Decimal('0.00')
    for charge in contract.level_charges.all():
        bp = charge.billed_paid_amount
        if bp is not None and Decimal(str(bp)) != Decimal('0'):
            charges_deduction += Decimal(str(bp))
        else:
            charges_deduction += Decimal(str(charge.estimated_amount))

    # Step 5: True contract adj_gross
    contract_adj_gross = total_clin_adj_gross - packaging_deduction - charges_deduction

    # Step 6: Collect all splits across all CLINs, grouped by company_name
    splits_by_company = defaultdict(list)
    for clin in clins:
        for split in clin.splits.all():
            splits_by_company[split.company_name].append(split)

    # Step 7: Determine percentage per company (first non-null percentage wins,
    # fall back to equal split across companies if none set)
    all_companies = list(splits_by_company.keys())
    company_percentages = {}
    for company, splits in splits_by_company.items():
        pct = next((s.percentage for s in splits if s.percentage is not None), None)
        company_percentages[company] = pct

    companies_with_pct = [c for c in all_companies if company_percentages[c] is not None]
    if not companies_with_pct:
        # No percentages set at all  equal split across companies
        n = len(all_companies)
        if n == 0:
            return JsonResponse({'success': True, 'updated_splits': 0, 'skipped_clins': []})
        base_pct = (Decimal('100.0') / Decimal(n)).quantize(Decimal('0.1'))
        for company in all_companies:
            company_percentages[company] = base_pct
    elif len(companies_with_pct) < len(all_companies):
        # Some companies have percentages, some don't  skip the ones without and report
        skipped = [c for c in all_companies if company_percentages[c] is None]
        return JsonResponse({
            'success': False,
            'error': f'Some companies have no percentage set: {", ".join(skipped)}. '
                     f'Set percentages for all companies before recalculating.',
            'updated_splits': 0,
            'skipped_clins': [],
        })

    # Validate percentages sum to ~100
    total_pct = sum(company_percentages[c] for c in all_companies)
    if not (Decimal('99.9') <= total_pct <= Decimal('100.1')):
        return JsonResponse({
            'success': False,
            'error': f'Company percentages sum to {total_pct}%, not 100%. '
                     f'Adjust percentages before recalculating.',
            'updated_splits': 0,
            'skipped_clins': [],
        })

    # Step 8: Compute split_value per company and write to ALL that company's
    # ClinSplit rows (each gets the same value  company's share of contract total)
    updated_count = 0
    for company, splits in splits_by_company.items():
        pct = company_percentages[company]
        company_split_value = (pct / Decimal('100.0')) * contract_adj_gross
        for split in splits:
            split.split_value = company_split_value
            split.save(update_fields=['split_value', 'modified_at'])
            updated_count += 1

    return JsonResponse({
        'success': True,
        'updated_splits': updated_count,
        'skipped_clins': [],
        'contract_adj_gross': str(contract_adj_gross),
    })


@conditional_login_required
@require_http_methods(['POST'])
def log_split_paid(request, contract_pk):
    """
    Accepts a total paid amount for one company and distributes it
    proportionally across that company's ClinSplit rows on this contract,
    using split_value as the weight. NULL/zero split_value rows get $0.
    If ALL rows have NULL/zero split_value, distributes equally.

    Request body (JSON):
        {
            "company_name": "STATZ",
            "total_paid": "1250.00"
        }

    Returns:
        {
            "success": true,
            "company_name": "STATZ",
            "total_paid": "1250.00",
            "company_total_paid": "1250.00",
            "splits": [
                {"split_id": 7, "item_number": "0001", "split_value": "500.00", "split_paid": "500.00"},
                ...
            ],
            "discrepancy": false,
            "discrepancy_amount": "0.00"
        }
    """
    from ..models import Contract

    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)

    contract = get_object_or_404(
        Contract.objects.filter(company=company), pk=contract_pk
    )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    company_name = (data.get('company_name') or '').strip()
    if not company_name:
        return JsonResponse({'success': False, 'error': 'company_name is required'}, status=400)

    total_paid = _parse_decimal(data.get('total_paid'))
    if total_paid is None:
        return JsonResponse({'success': False, 'error': 'total_paid is required'}, status=400)

    splits = list(
        ClinSplit.objects.filter(
            clin__contract=contract,
            company_name__iexact=company_name,
        ).select_related('clin').order_by('clin__item_number')
    )

    if not splits:
        return JsonResponse(
            {'success': False, 'error': f'No splits found for company "{company_name}"'},
            status=404,
        )

    weights = [
        Decimal(str(s.split_value)) if s.split_value else Decimal('0')
        for s in splits
    ]
    total_weight = sum(weights)

    if total_weight == 0:
        n = len(splits)
        base = (total_paid / Decimal(n)).quantize(Decimal('0.01'))
        allocated = [base] * n
        allocated[0] += total_paid - sum(allocated)
    else:
        allocated = []
        running = Decimal('0')
        for i, weight in enumerate(weights):
            if i == len(weights) - 1:
                allocated.append(total_paid - running)
            else:
                share = (weight / total_weight * total_paid).quantize(Decimal('0.01'))
                allocated.append(share)
                running += share

    for split, paid_amount in zip(splits, allocated):
        split.split_paid = paid_amount
        split.save(update_fields=['split_paid', 'modified_at'])

    total_split_value = sum(
        Decimal(str(s.split_value)) if s.split_value else Decimal('0')
        for s in splits
    )
    discrepancy_amount = total_paid - total_split_value
    has_discrepancy = abs(discrepancy_amount) > Decimal('0.01')

    result_splits = [
        {
            'split_id': s.id,
            'item_number': s.clin.item_number,
            'split_value': str(s.split_value) if s.split_value is not None else None,
            'split_paid': str(paid),
        }
        for s, paid in zip(splits, allocated)
    ]

    company_total_paid = sum(allocated)

    return JsonResponse({
        'success': True,
        'company_name': company_name,
        'total_paid': str(total_paid),
        'company_total_paid': str(company_total_paid),
        'splits': result_splits,
        'discrepancy': has_discrepancy,
        'discrepancy_amount': str(discrepancy_amount),
    })
