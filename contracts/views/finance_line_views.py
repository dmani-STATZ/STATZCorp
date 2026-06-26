import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from STATZWeb.decorators import conditional_login_required
from ..models import Clin, ClinShipment, Contract, ContractFinanceLine, ContractLevelCharge, FinanceLinePayment
from suppliers.models import Supplier

logger = logging.getLogger(__name__)


def _active_company_or_403(request):
    company = getattr(request, 'active_company', None)
    if company is None:
        raise PermissionDenied("An active company is required.")
    return company


def _contract_finance_line_company_qs(request):
    """Restrict finance-line mutations to the user's active company (via CLIN → Contract)."""
    company = getattr(request, 'active_company', None)
    if not company:
        return ContractFinanceLine.objects.none()
    return ContractFinanceLine.objects.filter(clin__contract__company=company)


@conditional_login_required
@require_http_methods(["POST"])
def add_finance_line(request):
    """Add a new finance line to a CLIN."""
    try:
        data = json.loads(request.body)
        clin_id = data.get('clin_id')
        line_type = (data.get('line_type') or '').strip()
        description = (data.get('description') or '').strip()
        amount_billed = data.get('amount_billed')

        if not clin_id:
            return JsonResponse({'success': False, 'error': 'clin_id required'}, status=400)
        if not line_type:
            return JsonResponse({'success': False, 'error': 'line_type required'}, status=400)
        if amount_billed is None:
            return JsonResponse({'success': False, 'error': 'amount_billed required'}, status=400)

        company = getattr(request, 'active_company', None)
        if not company:
            return JsonResponse({'success': False, 'error': 'No active company'}, status=403)
        clin = get_object_or_404(
            Clin.objects.filter(contract__company=company),
            id=clin_id,
        )

        finance_line = ContractFinanceLine.objects.create(
            clin=clin,
            partial=None,
            line_type=line_type,
            description=description,
            amount_billed=Decimal(str(amount_billed)),
            created_by=request.user,
            modified_by=request.user,
        )

        return JsonResponse({
            'success': True,
            'finance_line_id': finance_line.id,
            'finance_line': {
                'id': finance_line.id,
                'line_type': finance_line.line_type,
                'description': finance_line.description,
                'amount_billed': float(finance_line.amount_billed),
                'amount_paid': float(finance_line.amount_paid),
                'amount_remaining': float(finance_line.amount_remaining),
                'payment_status': finance_line.payment_status,
            }
        })
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        logger.error(f"add_finance_line error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@conditional_login_required
@require_http_methods(["GET"])
def get_finance_lines(request, clin_id):
    """Return all finance lines for a CLIN with computed totals."""
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)
    clin = get_object_or_404(
        Clin.objects.filter(contract__company=company),
        id=clin_id,
    )
    lines = ContractFinanceLine.objects.filter(
        clin=clin, partial__isnull=True
    ).order_by('created_on')

    lines_data = []
    for line in lines:
        lines_data.append({
            'id': line.id,
            'line_type': line.line_type,
            'description': line.description or '',
            'amount_billed': float(line.amount_billed),
            'amount_paid': float(line.amount_paid),
            'amount_remaining': float(line.amount_remaining),
            'payment_status': line.payment_status,
        })

    total_billed = sum(l['amount_billed'] for l in lines_data)
    total_paid = sum(l['amount_paid'] for l in lines_data)

    item_val = float(clin.item_value or 0)
    quote_val = float(clin.quote_value or 0)
    gross = item_val - quote_val
    adj_gross = gross - total_billed

    return JsonResponse({
        'success': True,
        'finance_lines': lines_data,
        'totals': {
            'total_billed': total_billed,
            'total_paid': total_paid,
            'gross': gross,
            'adj_gross': adj_gross,
        }
    })


@conditional_login_required
@require_http_methods(["POST"])
def log_finance_line_payment(request, finance_line_id):
    """Append a payment record to a finance line. Never updates existing records."""
    try:
        company = getattr(request, 'active_company', None)
        if not company:
            return JsonResponse({'success': False, 'error': 'No active company'}, status=403)

        data = json.loads(request.body)
        amount = data.get('payment_amount')
        payment_date = data.get('payment_date')
        note = (data.get('payment_info') or '').strip()

        if not amount:
            return JsonResponse({'success': False, 'error': 'payment_amount required'}, status=400)
        if not payment_date:
            return JsonResponse({'success': False, 'error': 'payment_date required'}, status=400)

        parsed_date = parse_date(str(payment_date))
        if parsed_date is None:
            return JsonResponse({'success': False, 'error': 'Invalid payment_date'}, status=400)

        finance_line = get_object_or_404(
            _contract_finance_line_company_qs(request),
            id=finance_line_id,
        )

        FinanceLinePayment.objects.create(
            finance_line=finance_line,
            amount=Decimal(str(amount)),
            payment_date=parsed_date,
            note=note or None,
            created_by=request.user,
            modified_by=request.user,
        )

        finance_line = ContractFinanceLine.objects.get(pk=finance_line.pk)

        return JsonResponse({
            'success': True,
            'new_total': float(finance_line.amount_paid),
            'amount_remaining': float(finance_line.amount_remaining),
            'payment_status': finance_line.payment_status,
            'message': 'Payment logged successfully'
        })
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        logger.error(f"log_finance_line_payment error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@conditional_login_required
@require_http_methods(["GET"])
def get_finance_line_payments(request, finance_line_id):
    """Return all payment records for a finance line."""
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)
    finance_line = get_object_or_404(
        _contract_finance_line_company_qs(request),
        id=finance_line_id,
    )
    payments = FinanceLinePayment.objects.filter(
        finance_line=finance_line
    ).order_by('payment_date', 'created_on')

    payments_data = [{
        'id': p.id,
        'amount': float(p.amount),
        'payment_date': p.payment_date.isoformat(),
        'note': p.note or '',
        'created_by': p.created_by.get_full_name() if p.created_by else 'System',
        'created_on': p.created_on.isoformat(),
    } for p in payments]

    return JsonResponse({
        'success': True,
        'payments': payments_data,
        'total_paid': float(finance_line.amount_paid),
        'amount_remaining': float(finance_line.amount_remaining),
        'payment_status': finance_line.payment_status,
    })


@conditional_login_required
@require_http_methods(["DELETE"])
def delete_finance_line(request, finance_line_id):
    """Hard delete a finance line and all its payment records."""
    try:
        company = getattr(request, 'active_company', None)
        if not company:
            return JsonResponse({'success': False, 'error': 'No active company'}, status=403)
        finance_line = get_object_or_404(
            _contract_finance_line_company_qs(request),
            id=finance_line_id,
        )
        clin_id = finance_line.clin_id
        finance_line.delete()  # CASCADE deletes FinanceLinePayment records too
        return JsonResponse({
            'success': True,
            'clin_id': clin_id,
            'message': 'Finance line deleted'
        })
    except Exception as e:
        logger.error(f"delete_finance_line error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@conditional_login_required
@require_http_methods(["GET"])
def get_partial_finance_lines(request, shipment_id):
    """Return all finance lines for a specific partial shipment."""
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)
    shipment = get_object_or_404(
        ClinShipment.objects.select_related('clin__contract'),
        id=shipment_id,
        clin__contract__company=company,
    )
    lines = ContractFinanceLine.objects.filter(
        partial=shipment
    ).order_by('created_on')

    lines_data = []
    for line in lines:
        lines_data.append({
            'id': line.id,
            'line_type': line.line_type,
            'description': line.description or '',
            'amount_billed': float(line.amount_billed),
            'amount_paid': float(line.amount_paid),
            'amount_remaining': float(line.amount_remaining),
            'payment_status': line.payment_status,
        })

    total_billed = sum(l['amount_billed'] for l in lines_data)

    return JsonResponse({
        'success': True,
        'finance_lines': lines_data,
        'totals': {
            'total_billed': total_billed,
        }
    })


@conditional_login_required
@require_http_methods(["POST"])
def add_partial_finance_line(request, shipment_id):
    """Add a new finance line scoped to a partial shipment."""
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)
    try:
        data = json.loads(request.body)
        shipment = get_object_or_404(
            ClinShipment.objects.select_related('clin'),
            id=shipment_id,
            clin__contract__company=company,
        )
        line_type = (data.get('line_type') or '').strip()
        description = (data.get('description') or '').strip()
        amount_billed = data.get('amount_billed')

        if not line_type:
            return JsonResponse({'success': False, 'error': 'line_type required'}, status=400)
        if amount_billed is None:
            return JsonResponse({'success': False, 'error': 'amount_billed required'}, status=400)

        finance_line = ContractFinanceLine.objects.create(
            clin=shipment.clin,
            partial=shipment,
            line_type=line_type,
            description=description,
            amount_billed=Decimal(str(amount_billed)),
            created_by=request.user,
            modified_by=request.user,
        )

        return JsonResponse({
            'success': True,
            'finance_line': {
                'id': finance_line.id,
                'line_type': finance_line.line_type,
                'description': finance_line.description,
                'amount_billed': float(finance_line.amount_billed),
                'amount_paid': float(finance_line.amount_paid),
                'amount_remaining': float(finance_line.amount_remaining),
                'payment_status': finance_line.payment_status,
            }
        })
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        logger.error(f"add_partial_finance_line error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@conditional_login_required
@require_http_methods(["POST"])
def add_partial_shipment(request):
    """Add a new partial shipment to a CLIN with optional financial fields."""
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)
    try:
        data = json.loads(request.body)
        clin_id = data.get('clin_id')
        if not clin_id:
            return JsonResponse({'success': False, 'error': 'clin_id required'}, status=400)

        clin = get_object_or_404(
            Clin.objects.filter(contract__company=company),
            id=clin_id,
        )

        ship_qty_raw = data.get('ship_qty')
        ship_qty = float(ship_qty_raw) if ship_qty_raw not in (None, '') else None

        def auto_calc(field, qty, unit):
            val = data.get(field)
            if val not in (None, ''):
                return Decimal(str(val))
            if qty and unit:
                return Decimal(str(qty)) * Decimal(str(unit))
            return None

        quote_value = auto_calc(
            'quote_value', ship_qty,
            clin.price_per_unit
        )
        item_value = auto_calc(
            'item_value', ship_qty,
            clin.unit_price
        )

        paid_amount_raw = data.get('paid_amount')
        wawf_payment_raw = data.get('wawf_payment')

        ship_date_raw = data.get('ship_date')
        ship_date = parse_date(str(ship_date_raw)) if ship_date_raw else None

        shipment = ClinShipment.objects.create(
            clin=clin,
            name=data.get('name') or None,
            ship_qty=ship_qty,
            uom=data.get('uom') or clin.uom or '',
            ship_date=ship_date,
            comments=data.get('comments') or '',
            quote_value=quote_value,
            item_value=item_value,
            paid_amount=Decimal(str(paid_amount_raw)) if paid_amount_raw not in (None, '') else None,
            wawf_payment=Decimal(str(wawf_payment_raw)) if wawf_payment_raw not in (None, '') else None,
            created_by=request.user,
            modified_by=request.user,
        )

        # Sync clin ship_qty and ship_date rollup fields
        from ..views.shipment_views import _sync_clin_ship_fields
        _sync_clin_ship_fields(clin, request.user)

        # Backfill unit prices on CLIN if missing but derivable from totals
        # (one-time self-healing write for migrated contracts)
        if (clin.unit_price is None and
                clin.item_value and
                clin.order_qty and
                float(clin.order_qty) != 0):
            try:
                clin.unit_price = (
                    Decimal(str(clin.item_value)) /
                    Decimal(str(clin.order_qty))
                )
                clin.save(update_fields=['unit_price'])
            except (InvalidOperation, ZeroDivisionError):
                pass

        if (clin.price_per_unit is None and
                clin.quote_value and
                clin.order_qty and
                float(clin.order_qty) != 0):
            try:
                clin.price_per_unit = (
                    Decimal(str(clin.quote_value)) /
                    Decimal(str(clin.order_qty))
                )
                clin.save(update_fields=['price_per_unit'])
            except (InvalidOperation, ZeroDivisionError):
                pass

        # --- PaymentHistory rollup for paid_amount and wawf_payment ---
        from django.contrib.contenttypes.models import ContentType
        from ..models import PaymentHistory

        today = shipment.ship_date or __import__('datetime').date.today()

        shipment_content_type = ContentType.objects.get_for_model(ClinShipment)

        ROLLUP_FIELDS = [
            ('paid_amount', 'partial_paid_amount'),
            ('wawf_payment', 'partial_wawf_payment'),
        ]

        had_payment_rollup = False
        for shipment_field, shipment_payment_type in ROLLUP_FIELDS:
            value = getattr(shipment, shipment_field)
            if not value:
                continue

            had_payment_rollup = True
            PaymentHistory.objects.create(
                content_type=shipment_content_type,
                object_id=shipment.id,
                payment_type=shipment_payment_type,
                payment_amount=value,
                payment_date=today,
                payment_info='Initial value set on shipment creation',
                reference_number='',
                created_by=request.user,
                modified_by=request.user,
                company=clin.company,
            )

        if had_payment_rollup:
            from .shipment_views import _recompute_clin_payment_rollup
            _recompute_clin_payment_rollup(clin, request.user)
        # --- end PaymentHistory rollup ---

        return JsonResponse({
            'success': True,
            'shipment': {
                'id': shipment.id,
                'ship_date': shipment.ship_date.isoformat() if shipment.ship_date else None,
                'ship_qty': shipment.ship_qty,
                'uom': shipment.uom,
                'quote_value': float(shipment.quote_value) if shipment.quote_value else 0,
                'item_value': float(shipment.item_value) if shipment.item_value else 0,
                'paid_amount': float(shipment.paid_amount) if shipment.paid_amount else 0,
                'wawf_payment': float(shipment.wawf_payment) if shipment.wawf_payment else 0,
                'comments': shipment.comments or '',
                'auto_quote_value': float(shipment.auto_quote_value),
                'auto_item_value': float(shipment.auto_item_value),
            }
        })
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        logger.error(f"add_partial_shipment error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@conditional_login_required
@require_http_methods(["GET"])
def get_partial_auto_calc(request):
    """Return auto-calculated quote_value and item_value for a given clin and ship_qty."""
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)
    clin_id = request.GET.get('clin_id')
    ship_qty = request.GET.get('ship_qty')
    if not clin_id or not ship_qty:
        return JsonResponse({'success': False, 'error': 'clin_id and ship_qty required'}, status=400)
    try:
        clin = get_object_or_404(
            Clin.objects.filter(contract__company=company),
            id=clin_id,
        )
        qty = Decimal(str(ship_qty))
        price_per_unit = Decimal(str(clin.price_per_unit or 0))
        unit_price = Decimal(str(clin.unit_price or 0))
        return JsonResponse({
            'success': True,
            'auto_quote_value': float(qty * price_per_unit),
            'auto_item_value': float(qty * unit_price),
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@conditional_login_required
@require_http_methods(["POST"])
def set_clin_unit_prices(request, clin_id):
    """Set CLIN unit_price and/or price_per_unit (fallback for un-backfillable legacy CLINs)."""
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    clin = get_object_or_404(
        Clin.objects.filter(contract__company=company),
        id=clin_id,
    )

    update_fields = []
    errors = []

    if 'unit_price' in data and data['unit_price'] is not None and data['unit_price'] != '':
        try:
            unit_price = Decimal(str(data['unit_price']))
            if unit_price <= 0:
                errors.append('Unit price must be greater than zero')
            else:
                clin.unit_price = unit_price
                update_fields.append('unit_price')
        except (InvalidOperation, ValueError):
            errors.append('Invalid unit price')

    if 'price_per_unit' in data and data['price_per_unit'] is not None and data['price_per_unit'] != '':
        try:
            price_per_unit = Decimal(str(data['price_per_unit']))
            if price_per_unit <= 0:
                errors.append('Price per unit must be greater than zero')
            else:
                clin.price_per_unit = price_per_unit
                update_fields.append('price_per_unit')
        except (InvalidOperation, ValueError):
            errors.append('Invalid price per unit')

    if errors:
        return JsonResponse({'success': False, 'error': '; '.join(errors)}, status=400)

    if not update_fields:
        return JsonResponse(
            {'success': False, 'error': 'Provide at least one price to save'},
            status=400,
        )

    clin.save(update_fields=update_fields)

    return JsonResponse({
        'success': True,
        'unit_price': str(clin.unit_price) if clin.unit_price is not None else None,
        'price_per_unit': str(clin.price_per_unit) if clin.price_per_unit is not None else None,
    })


@conditional_login_required
@require_http_methods(["POST"])
def add_contract_level_charge(request, contract_pk):
    company = _active_company_or_403(request)
    contract = get_object_or_404(Contract, pk=contract_pk, company=company)

    label = request.POST.get("label", "").strip()
    estimated_amount = request.POST.get("estimated_amount", "").strip()
    supplier_id = request.POST.get("supplier_id") or None
    action_type_raw = request.POST.get("action_type", "charge").strip()
    action_type = action_type_raw if action_type_raw in ('charge', 'advance') else 'charge'

    if not label:
        return JsonResponse({"success": False, "error": "Label is required."}, status=400)
    if not estimated_amount:
        return JsonResponse({"success": False, "error": "Estimated amount is required."}, status=400)

    try:
        amount = Decimal(estimated_amount)
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid amount."}, status=400)

    supplier = None
    if supplier_id:
        supplier = get_object_or_404(Supplier, pk=supplier_id)

    if action_type == 'advance':
        # CIA: amount is what was paid, not an estimate
        charge = ContractLevelCharge.objects.create(
            contract=contract,
            label=label,
            action_type='advance',
            estimated_amount=Decimal('0.00'),
            billed_paid_amount=amount,
            supplier=supplier,
        )
    else:
        charge = ContractLevelCharge.objects.create(
            contract=contract,
            label=label,
            action_type='charge',
            estimated_amount=amount,
            supplier=supplier,
        )

    return JsonResponse({
        "success": True,
        "charge_id": charge.id,
        "label": charge.label,
        "supplier_name": charge.supplier.name if charge.supplier else "",
        "estimated_amount": str(charge.estimated_amount),
        "billed_paid_amount": str(charge.billed_paid_amount or ''),
        "action_type": charge.action_type,
    })


@conditional_login_required
@require_http_methods(["POST"])
def delete_contract_level_charge(request, charge_pk):
    company = _active_company_or_403(request)
    charge = get_object_or_404(
        ContractLevelCharge, pk=charge_pk, contract__company=company
    )
    charge.delete()
    return JsonResponse({"success": True})


@conditional_login_required
@require_http_methods(["GET"])
def charge_detail_panel(request, charge_pk):
    company = _active_company_or_403(request)
    charge = get_object_or_404(
        ContractLevelCharge.objects.select_related("supplier", "contract"),
        pk=charge_pk,
        contract__company=company,
    )
    content_type_id = ContentType.objects.get_for_model(ContractLevelCharge).id
    return render(request, "contracts/partials/charge_detail_panel.html", {
        "charge": charge,
        "content_type_id": content_type_id,
    })
