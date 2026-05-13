"""
Contract Packaging endpoints.

ContractPackaging financial flow:
- quote_amount and amount_paid are written via the PaymentHistory popup
  (entity_type=`contract_packaging`, payment types `packaging_quote` /
  `packaging_paid`) — see payment_history_views.payment_history_api.
- invoice_number and payment_date are edited inline on Finance Audit via
  `update_packaging_finance`.
- packhouse and notes are edited inline on Contract Review and from the
  ⓘ modal on Contract Management via `update_packaging_details`.
"""
from datetime import date

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, ContractPackaging


@conditional_login_required
@require_http_methods(["POST"])
def update_packaging_details(request, pk):
    """
    Update non-financial ContractPackaging fields: packhouse, notes.
    Called from contract_review.html inline edit form and the contract
    management ⓘ modal.

    Financial fields (quote_amount, amount_paid, payment_date,
    invoice_number) are updated exclusively via the PaymentHistory popup
    on finance_audit.html or `update_packaging_finance`.
    """
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'error': 'No active company'}, status=403)

    try:
        packaging = ContractPackaging.objects.select_related(
            'packhouse', 'contract'
        ).get(pk=pk, contract__company=company)
    except ContractPackaging.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    field = request.POST.get('field')
    value = request.POST.get('value', '').strip()

    allowed_fields = ['packhouse', 'notes']
    if field not in allowed_fields:
        return JsonResponse({'error': f'Field {field} not editable here'}, status=400)

    if field == 'packhouse':
        if not value:
            return JsonResponse({'error': 'Packhouse is required'}, status=400)
        try:
            from suppliers.models import Supplier
            supplier = Supplier.objects.get(pk=int(value))
            packaging.packhouse = supplier
        except (Supplier.DoesNotExist, ValueError):
            return JsonResponse({'error': 'Invalid supplier'}, status=400)
        display_value = supplier.name
    else:  # notes
        packaging.notes = value or None
        display_value = value or ''

    packaging.modified_by = request.user
    packaging.save(update_fields=[field, 'modified_by', 'modified_on'])

    return JsonResponse({'success': True, 'display_value': display_value})


@conditional_login_required
@require_http_methods(["POST"])
def update_packaging_finance(request, pk):
    """
    Update Finance-owned ContractPackaging fields: invoice_number, payment_date.
    quote_amount and amount_paid are handled via PaymentHistory popup.
    """
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'error': 'No active company'}, status=403)

    try:
        packaging = ContractPackaging.objects.get(pk=pk, contract__company=company)
    except ContractPackaging.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    field = request.POST.get('field')
    value = request.POST.get('value', '').strip()

    allowed_fields = ['invoice_number', 'payment_date']
    if field not in allowed_fields:
        return JsonResponse({'error': f'Field {field} not editable here'}, status=400)

    if field == 'invoice_number':
        packaging.invoice_number = value or None
        display_value = value or ''
    else:  # payment_date
        if value:
            try:
                packaging.payment_date = date.fromisoformat(value)
                display_value = packaging.payment_date.strftime('%m/%d/%Y')
            except ValueError:
                return JsonResponse({'error': 'Invalid date format'}, status=400)
        else:
            packaging.payment_date = None
            display_value = ''

    packaging.modified_by = request.user
    packaging.save(update_fields=[field, 'modified_by', 'modified_on'])

    return JsonResponse({'success': True, 'display_value': display_value})


@conditional_login_required
@require_http_methods(["GET"])
def get_packaging_modal(request, contract_pk):
    """
    Returns JSON for the packaging info/notes modal on contract_management.html.
    Notes are editable from the modal; all other fields are read-only.
    """
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'error': 'No active company'}, status=403)

    try:
        contract = Contract.objects.get(pk=contract_pk, company=company)
        pkg = contract.packaging  # may raise DoesNotExist
    except (Contract.DoesNotExist, ContractPackaging.DoesNotExist):
        return JsonResponse({'has_packaging': False})

    return JsonResponse({
        'has_packaging': True,
        'packaging_id': pkg.id,
        'packhouse_name': pkg.packhouse.name if pkg.packhouse else '—',
        'cage_code': pkg.packhouse.cage_code if pkg.packhouse else '—',
        'packhouse_id': pkg.packhouse.id if pkg.packhouse else None,
        'quote_amount': str(pkg.quote_amount) if pkg.quote_amount is not None else None,
        'amount_paid': str(pkg.amount_paid) if pkg.amount_paid is not None else None,
        'notes': pkg.notes or '',
        'modified_by': pkg.modified_by.get_full_name() if pkg.modified_by else '—',
        'modified_on': pkg.modified_on.strftime('%m/%d/%Y') if pkg.modified_on else '—',
    })
