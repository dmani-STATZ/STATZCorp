import json
import logging
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, Clin, PurchaseOrder, POLineItem
from suppliers.models import Supplier

logger = logging.getLogger('django')


def _active_company_or_403(request):
    company = getattr(request, 'active_company', None)
    if company is None:
        raise PermissionDenied("An active company is required.")
    return company


def _to_decimal(value):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _build_line_activity(clin):
    """Seeded line text: NSN code / description / P/N (matches legacy PO)."""
    parts = []
    nsn = clin.nsn
    if nsn:
        if nsn.nsn_code:
            parts.append(nsn.nsn_code)
        if nsn.description:
            parts.append(nsn.description)
        if nsn.part_number:
            parts.append(f"P/N: {nsn.part_number}")
    return "\n".join(parts)


def _resolve_po_supplier(contract):
    """(supplier_or_None, needs_picker, distinct_supplier_list).
    Exactly one distinct CLIN supplier -> auto-set; 0 or >1 -> picker."""
    supplier_ids = list(
        Clin.objects.filter(contract=contract, supplier__isnull=False)
        .values_list('supplier_id', flat=True).distinct()
    )
    suppliers = list(Supplier.objects.filter(id__in=supplier_ids).order_by('name'))
    if len(supplier_ids) == 1:
        return suppliers[0], False, suppliers
    return None, True, suppliers


def _seed_po_lines_from_clins(po, contract):
    """One priced line per CLIN. RUNS ONCE AT CREATION ONLY — never re-seed."""
    clins = (
        Clin.objects.filter(contract=contract)
        .select_related('nsn')
        .order_by('item_number', 'id')
    )
    order = 0
    for clin in clins:
        order += 1
        qty = _to_decimal(clin.order_qty)
        rate = clin.price_per_unit
        if qty is not None and rate is not None:
            amount = (qty * rate).quantize(Decimal('0.01'))
        else:
            amount = clin.quote_value
        POLineItem.objects.create(
            purchase_order=po, sort_order=order,
            activity=_build_line_activity(clin),
            qty=qty, rate=rate, amount=amount,
        )


def _get_or_create_po(contract, request):
    try:
        return PurchaseOrder.objects.get(contract=contract), False
    except PurchaseOrder.DoesNotExist:
        supplier, _needs, _list = _resolve_po_supplier(contract)
        po = PurchaseOrder(
            company=contract.company, contract=contract, supplier=supplier,
            po_number=contract.po_number or '',
            po_date=timezone.now().date(),
            created_by=request.user, modified_by=request.user,
        )

        # --- Vendor snapshot (from resolved supplier) ---
        if supplier:
            po.vendor_name = supplier.name or ''
            addr = getattr(supplier, 'physical_address', None)
            if addr:
                addr_parts = [
                    p for p in [
                        getattr(addr, 'address_line_1', ''),
                        getattr(addr, 'address_line_2', ''),
                        ' '.join(filter(None, [
                            getattr(addr, 'city', ''),
                            getattr(addr, 'state', ''),
                            getattr(addr, 'zip', ''),
                        ])),
                    ] if p and p.strip()
                ]
                po.vendor_address = '\n'.join(addr_parts)

        # --- Ship-To snapshot (from CompanyPOProfile) ---
        company = contract.company
        profile = getattr(company, 'po_profile', None)
        if profile:
            po.ship_to_name = profile.ship_to_name or ''
            contact_parts = [
                p for p in [
                    profile.ship_to_attn,
                    profile.ship_to_title,
                    profile.contact_note,
                    profile.phone,
                    profile.email,
                ] if p and p.strip()
            ]
            po.ship_to_contact = '\n'.join(contact_parts)

        po.save()
        _seed_po_lines_from_clins(po, contract)
        return po, True


@conditional_login_required
def purchase_order_page(request, contract_id):
    company = _active_company_or_403(request)
    if not company.enable_po_generator:
        raise PermissionDenied("PO generator is not enabled for this company.")
    contract = get_object_or_404(
        Contract.objects.select_related('company', 'idiq_contract'),
        id=contract_id, company=company,
    )
    po, _created = _get_or_create_po(contract, request)
    supplier, needs_picker, clin_suppliers = _resolve_po_supplier(contract)
    if supplier and po.supplier_id is None:
        po.supplier = supplier
        po.modified_by = request.user
        po.save(update_fields=['supplier', 'modified_by', 'modified_on'])
    return render(request, 'contracts/purchase_order_page.html', {
        'contract': contract,
        'po': po,
        'line_items': po.line_items.all(),
        'needs_supplier_picker': needs_picker,
        'clin_suppliers': clin_suppliers,
        'idiq_number': contract.idiq_contract.contract_number if contract.idiq_contract else '',
    })


@conditional_login_required
@require_POST
def update_purchase_order(request, po_id):
    company = _active_company_or_403(request)
    po = get_object_or_404(PurchaseOrder, id=po_id, company=company)
    po.po_number = (request.POST.get('po_number') or '').strip()
    date_str = (request.POST.get('po_date') or '').strip()
    po.po_date = parse_date(date_str) if date_str else None
    po.footer = request.POST.get('footer') or ''
    po.vendor_name = (request.POST.get('vendor_name') or '').strip()
    po.vendor_address = request.POST.get('vendor_address') or ''
    po.ship_to_name = (request.POST.get('ship_to_name') or '').strip()
    po.ship_to_contact = request.POST.get('ship_to_contact') or ''
    supplier_id = request.POST.get('supplier_id')
    if supplier_id:
        po.supplier = get_object_or_404(Supplier, id=supplier_id)
    po.modified_by = request.user
    po.save()
    return JsonResponse({'success': True})


@conditional_login_required
@require_POST
def add_po_line(request, po_id):
    company = _active_company_or_403(request)
    po = get_object_or_404(PurchaseOrder, id=po_id, company=company)
    next_order = po.line_items.count() + 1
    line = POLineItem.objects.create(
        purchase_order=po, sort_order=next_order,
        activity=request.POST.get('activity') or '',
        qty=_to_decimal(request.POST.get('qty')),
        rate=_to_decimal(request.POST.get('rate')),
        amount=_to_decimal(request.POST.get('amount')),
    )
    return JsonResponse({'success': True, 'line': {
        'id': line.id, 'sort_order': line.sort_order, 'activity': line.activity,
        'qty': str(line.qty) if line.qty is not None else '',
        'rate': str(line.rate) if line.rate is not None else '',
        'amount': str(line.amount) if line.amount is not None else '',
    }})


@conditional_login_required
@require_POST
def update_po_line(request, line_id):
    company = _active_company_or_403(request)
    line = get_object_or_404(POLineItem, id=line_id, purchase_order__company=company)
    if 'activity' in request.POST:
        line.activity = request.POST.get('activity') or ''
    if 'qty' in request.POST:
        line.qty = _to_decimal(request.POST.get('qty'))
    if 'rate' in request.POST:
        line.rate = _to_decimal(request.POST.get('rate'))
    if 'amount' in request.POST:
        line.amount = _to_decimal(request.POST.get('amount'))
    line.save()
    return JsonResponse({'success': True})


@conditional_login_required
@require_POST
def delete_po_line(request, line_id):
    company = _active_company_or_403(request)
    line = get_object_or_404(POLineItem, id=line_id, purchase_order__company=company)
    line.delete()
    return JsonResponse({'success': True})


@conditional_login_required
@require_POST
def reorder_po_lines(request, po_id):
    company = _active_company_or_403(request)
    po = get_object_or_404(PurchaseOrder, id=po_id, company=company)
    try:
        ordered_ids = json.loads(request.body).get('ordered_ids', [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'success': False, 'error': 'Invalid payload'}, status=400)
    id_to_order = {int(pk): idx + 1 for idx, pk in enumerate(ordered_ids)}
    lines = list(po.line_items.filter(id__in=id_to_order.keys()))
    for line in lines:
        line.sort_order = id_to_order[line.id]
    POLineItem.objects.bulk_update(lines, ['sort_order'])
    return JsonResponse({'success': True})


@conditional_login_required
def purchase_order_print(request, po_id):
    company = _active_company_or_403(request)
    if not company.enable_po_generator:
        raise PermissionDenied("PO generator is not enabled for this company.")
    po = get_object_or_404(
        PurchaseOrder.objects.select_related(
            'contract', 'contract__idiq_contract', 'supplier',
            'supplier__physical_address', 'company',
        ),
        id=po_id, company=company,
    )
    profile = getattr(company, 'po_profile', None)
    line_items = list(po.line_items.all())
    total = sum((li.amount for li in line_items if li.amount is not None), Decimal('0'))
    return render(request, 'contracts/po_print.html', {
        'po': po,
        'contract': po.contract,
        'supplier': po.supplier,
        'profile': profile,
        'company': company,
        'line_items': line_items,
        'total': total,
        'idiq_number': po.contract.idiq_contract.contract_number if po.contract.idiq_contract else '',
        'logo_url': company.logo_url,
    })

