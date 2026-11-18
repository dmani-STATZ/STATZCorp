from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.views.decorators.csrf import csrf_exempt
import json
import logging
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date

from STATZWeb.decorators import conditional_login_required
from ..models import Clin, ClinShipment, PaymentHistory
from ..services.pod_status import compute_pod_status
from ..services.shipment_payments import (
    CENT,
    recompute_clin_payment_rollup,
    set_shipment_payment_total,
)

logger = logging.getLogger(__name__)


def _sync_clin_ship_fields(clin, user):
    """
    Recalculate clin.ship_qty, clin.ship_date, and clin.pod_date from all ClinShipment rows.
    - ship_qty = SUM of all shipment ship_qty values (None shipments excluded)
    - ship_date = MAX ship_date across all shipments that have a non-null ship_date
    - pod_date = MAX pod_date across shipments with a non-null pod_date, or None if none
    If pod_complete is set and the CLIN now has zero shipments or any shipment
    with a null pod_date, clear pod_complete in the same save.
    - paid_date = MAX shipment paid_date; wawf_recieved = MAX shipment
      wawf_payment_date. Only written when some shipment has that date, so an
      existing CLIN date is never overwritten with NULL.
    Transactions signals fire automatically on save.
    """
    agg = clin.shipments.aggregate(
        total_qty=Sum('ship_qty'),
        latest_date=Max('ship_date'),
        latest_pod_date=Max('pod_date'),
        latest_paid_date=Max('paid_date'),
        latest_wawf_payment_date=Max('wawf_payment_date'),
        shipment_count=Count('id'),
        missing_pod=Count('id', filter=Q(pod_date__isnull=True)),
    )
    clin.ship_qty = agg['total_qty'] or 0
    clin.ship_date = agg['latest_date']
    clin.pod_date = agg['latest_pod_date']
    clin.modified_by = user
    update_fields = [
        'ship_qty', 'ship_date', 'pod_date', 'modified_by', 'modified_on',
    ]
    if clin.pod_complete and (not agg['shipment_count'] or agg['missing_pod']):
        clin.pod_complete = False
        update_fields.append('pod_complete')
    for clin_field, agg_key in (
        ('paid_date', 'latest_paid_date'),
        ('wawf_recieved', 'latest_wawf_payment_date'),
    ):
        latest = agg[agg_key]
        if latest is not None and getattr(clin, clin_field) != latest:
            setattr(clin, clin_field, latest)
            update_fields.append(clin_field)
    clin.save(update_fields=update_fields)


def _pod_complete_success(clin, requested_true):
    qty_warning = bool(
        requested_true
        and clin.ship_qty is not None
        and clin.order_qty is not None
        and clin.ship_qty < clin.order_qty
    )
    return JsonResponse({
        'success': True,
        'pod_complete': bool(clin.pod_complete),
        'pod_status': compute_pod_status(clin),
        'pod_date': clin.pod_date.strftime('%m/%d/%Y') if clin.pod_date else '—',
        'qty_warning': qty_warning,
        'shipped_qty': float(clin.ship_qty) if clin.ship_qty is not None else None,
        'order_qty': float(clin.order_qty) if clin.order_qty is not None else None,
    })


@conditional_login_required
@require_http_methods(["POST"])
def clin_pod_complete_api(request, clin_id):
    """Set Clin.pod_complete. Checking is guarded; unchecking is always allowed."""
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)
    clin = get_object_or_404(
        Clin.objects.filter(contract__company=company),
        id=clin_id,
    )
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return JsonResponse(
            {'success': False, 'error': 'Body must be {"value": true} or {"value": false}.'},
            status=400,
        )
    if (
        not isinstance(data, dict)
        or set(data.keys()) != {'value'}
        or not isinstance(data.get('value'), bool)
    ):
        return JsonResponse(
            {'success': False, 'error': 'Body must be {"value": true} or {"value": false}.'},
            status=400,
        )
    value = data['value']
    if clin.pod_complete == value:
        return _pod_complete_success(clin, value)

    if value:
        rows = list(clin.shipments.values_list('id', 'pod_date'))
        missing_ids = [shipment_id for shipment_id, pod_date in rows if pod_date is None]
        if not rows or missing_ids:
            if not rows:
                error = 'This CLIN has no shipments, so it cannot be marked POD complete.'
                missing_ids = []
            else:
                error = 'Every shipment must have a POD date before this CLIN can be marked POD complete.'
            return JsonResponse(
                {
                    'success': False,
                    'error': error,
                    'missing_shipment_ids': missing_ids,
                },
                status=400,
            )

    clin.pod_complete = value
    clin.modified_by = request.user
    clin.save(update_fields=['pod_complete', 'modified_by', 'modified_on'])
    return _pod_complete_success(clin, value)


_recompute_clin_payment_rollup = recompute_clin_payment_rollup

MONEY_TOTAL_FIELDS = {
    'paid_amount_total': ('paid_amount', 'Paid'),
    'wawf_payment_total': ('wawf_payment', 'Customer Pay'),
}
MAX_MONEY_INTEGER_DIGITS = 13

# Shipment payment date key -> (label, matching money field).
PAYMENT_DATE_FIELDS = {
    'paid_date': ('Paid Date', 'paid_amount'),
    'wawf_payment_date': ('Customer Pay Date', 'wawf_payment'),
}
MONEY_FIELD_DATE = {
    money_field: date_key
    for date_key, (_label, money_field) in PAYMENT_DATE_FIELDS.items()
}


def parse_optional_date(raw, label):
    """Return a date, or None for None / blank. Raise ValueError otherwise."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ''):
        return None
    error = ValueError(f'{label} must be a valid date (YYYY-MM-DD).')
    if not isinstance(raw, str):
        raise error
    try:
        value = parse_date(raw.strip())
    except ValueError:
        raise error
    if value is None:
        raise error
    return value


def _parse_money_total(raw, label):
    """Return a non-negative Decimal with at most 2 places, or raise ValueError."""
    error = ValueError(
        f'{label} must be a number of 0 or more with at most 2 decimal places.'
    )
    if isinstance(raw, bool) or raw is None:
        raise error
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        raise error
    if not value.is_finite() or value < 0 or value.as_tuple().exponent < -2:
        raise error
    if value >= Decimal(10) ** MAX_MONEY_INTEGER_DIGITS:
        raise ValueError(f'{label} is too large.')
    return value.quantize(CENT)


@csrf_exempt
@require_http_methods(["POST"])
def create_shipment(request):
    """Create a new shipment."""
    logger.info("Create shipment endpoint hit")
    logger.debug(f"Request body: {request.body}")
    
    try:
        data = json.loads(request.body)
        logger.debug(f"Parsed data: {data}")
        
        clin_id = data.get('clin_id')
        if not clin_id:
            logger.error("No CLIN ID provided")
            raise ValueError('CLIN ID is required')
            
        clin = get_object_or_404(Clin, id=clin_id)
        logger.debug(f"Found CLIN: {clin.id}")
        
        if not data.get('ship_qty'):
            logger.error("No ship quantity provided")
            raise ValueError('Ship quantity is required')
            
        raw_ship_date = data.get('ship_date')
        ship_date = raw_ship_date if raw_ship_date not in (None, '') else None

        # Create new shipment
        shipment = ClinShipment.objects.create(
            clin=clin,
            ship_qty=float(data.get('ship_qty', 0.00)),
            uom=data.get('uom', clin.uom),  # Get UOM from data or default to what is in the CLIN
            ship_date=ship_date,
            comments=data.get('comments', ''),
            # Financial fields — nullable, optional
            quote_value=Decimal(str(data['quote_value'])) if data.get('quote_value') not in (None, '') else None,
            item_value=Decimal(str(data['item_value'])) if data.get('item_value') not in (None, '') else None,
            paid_amount=Decimal(str(data['paid_amount'])) if data.get('paid_amount') not in (None, '') else None,
            wawf_payment=Decimal(str(data['wawf_payment'])) if data.get('wawf_payment') not in (None, '') else None,
            created_by=request.user,
            modified_by=request.user,
        )

        _sync_clin_ship_fields(clin, request.user)

        logger.info(f"Successfully created shipment {shipment.id}")
        return JsonResponse({
            'success': True,
            'shipment_id': shipment.id,
            'ship_date': shipment.ship_date.isoformat() if shipment.ship_date else None,
        })
        
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)
    except TypeError as e:
        logger.error(f"Type error: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': f'Invalid data format: {str(e)}'
        }, status=400)
    except Exception as e:
        import traceback
        logger.error(f"Unexpected error: {str(e)}")
        logger.error(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)

@conditional_login_required
@require_http_methods(["PATCH"])
def update_shipment_name(request, shipment_id):
    """Update the name field on a ClinShipment."""
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip() or None
        shipment = get_object_or_404(
            ClinShipment,
            id=shipment_id,
            clin__contract__company=request.active_company
        )
        shipment.name = name
        shipment.modified_by = request.user
        shipment.save(update_fields=['name', 'modified_by', 'modified_on'])
        return JsonResponse({
            'success': True,
            'name': shipment.name,
            'display_name': shipment.name or None,
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def _money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _decimal_qty_differs(old, new):
    """True when two ship quantities are not the same Decimal value."""
    if old is None:
        return True
    return Decimal(str(old)) != Decimal(str(new))


@csrf_exempt
@require_http_methods(["POST"])
def update_shipment(request, shipment_id):
    """Update an existing shipment."""
    try:
        data = json.loads(request.body)
        company = getattr(request, 'active_company', None)
        if not company:
            return JsonResponse({'success': False, 'error': 'No active company'}, status=403)
        shipment = get_object_or_404(ClinShipment, id=shipment_id, clin__contract__company=company)

        money_totals = {}
        for key, (field, label) in MONEY_TOTAL_FIELDS.items():
            if key in data:
                try:
                    money_totals[field] = _parse_money_total(data[key], label)
                except ValueError as exc:
                    return JsonResponse(
                        {'success': False, 'error': str(exc), 'field': key},
                        status=400,
                    )

        payment_dates = {}
        for key, (label, _money_field) in PAYMENT_DATE_FIELDS.items():
            if key in data:
                try:
                    payment_dates[key] = parse_optional_date(data[key], label)
                except ValueError as exc:
                    return JsonResponse(
                        {'success': False, 'error': str(exc), 'field': key},
                        status=400,
                    )

        # Update shipment fields
        if 'name' in data:
            shipment.name = (data['name'] or '').strip() or None
        qty_changed = False
        if 'ship_qty' in data:
            old_qty = shipment.ship_qty
            shipment.ship_qty = float(data['ship_qty'])
            if shipment.ship_qty is not None and _decimal_qty_differs(old_qty, shipment.ship_qty):
                qty_changed = True
        if 'uom' in data:
            shipment.uom = data['uom']
        if 'ship_date' in data:
            sd = data['ship_date']
            shipment.ship_date = sd if sd not in (None, '') else None
        if 'comments' in data:
            shipment.comments = data['comments']
        if 'pod_date' in data:
            shipment.pod_date = data['pod_date'] or None
        if 'quote_value' in data:
            qv = data['quote_value']
            shipment.quote_value = Decimal(str(qv)) if qv not in (None, '') else None
        elif qty_changed and shipment.clin.price_per_unit is not None:
            shipment.quote_value = _money(shipment.auto_quote_value)
        if 'item_value' in data:
            iv = data['item_value']
            shipment.item_value = Decimal(str(iv)) if iv not in (None, '') else None
        elif qty_changed and shipment.clin.unit_price is not None:
            shipment.item_value = _money(shipment.auto_item_value)

        with transaction.atomic():
            for key, value in payment_dates.items():
                setattr(shipment, key, value)
            shipment.modified_by = request.user
            shipment.save()

            payment_changed = False
            for field, target in money_totals.items():
                if set_shipment_payment_total(
                    shipment,
                    field,
                    target,
                    request.user,
                    payment_date=getattr(shipment, MONEY_FIELD_DATE[field]),
                ):
                    payment_changed = True

            _sync_clin_ship_fields(shipment.clin, request.user)
            if payment_changed:
                recompute_clin_payment_rollup(shipment.clin, request.user)

        return JsonResponse({
            'success': True
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@csrf_exempt
@require_http_methods(["POST"])
def delete_shipment(request, shipment_id):
    """Delete a shipment."""
    try:
        shipment = get_object_or_404(ClinShipment, id=shipment_id)
        clin = shipment.clin
        with transaction.atomic():
            ledger_rows = list(PaymentHistory.objects.filter(
                content_type=ContentType.objects.get_for_model(ClinShipment),
                object_id=shipment.pk,
            ))
            for row in ledger_rows:
                row.delete()
            shipment.delete()
            _sync_clin_ship_fields(clin, request.user)
            recompute_clin_payment_rollup(clin, request.user)

        return JsonResponse({
            'success': True
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

# Optional: View for loading shipments via AJAX
@require_http_methods(["GET"])
def get_clin_shipments(request, clin_id):
    """Get HTML for shipments section."""
    from django.template.loader import render_to_string
    
    clin = get_object_or_404(Clin, id=clin_id)
    html = render_to_string('contracts/partials/clin_shipments.html', {
        'clin': clin,
        'mode': request.GET.get('mode', 'detail')
    })
    
    return JsonResponse({
        'success': True,
        'html': html
    })


@csrf_exempt
@require_http_methods(["POST"])
def complete_clin_shipping(request, clin_id):
    """
    Updates clin.ship_date and clin.ship_qty from the completed
    shipments. Transaction records are written automatically by signals.
    """
    try:
        data = json.loads(request.body)
        clin = get_object_or_404(Clin, id=clin_id)

        ship_date = data.get('ship_date')
        ship_qty = data.get('ship_qty')

        if not ship_date:
            raise ValueError('Ship date is required')
        if ship_qty is None:
            raise ValueError('Ship quantity is required')

        clin.ship_date = ship_date
        clin.ship_qty = float(ship_qty)
        clin.modified_by = request.user
        clin.save(update_fields=['ship_date', 'ship_qty', 'modified_by',
                                 'modified_on'])

        return JsonResponse({
            'success': True,
            'ship_date': ship_date,
            'ship_qty': float(ship_qty)
        })

    except ValueError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
