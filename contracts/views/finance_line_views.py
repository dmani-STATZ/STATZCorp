import json
import logging
from decimal import Decimal

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from STATZWeb.decorators import conditional_login_required
from ..models import Clin, ContractFinanceLine, FinanceLinePayment

logger = logging.getLogger(__name__)


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

        clin = get_object_or_404(Clin, id=clin_id)

        finance_line = ContractFinanceLine.objects.create(
            clin=clin,
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
        logger.error(f"add_finance_line error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@conditional_login_required
@require_http_methods(["GET"])
def get_finance_lines(request, clin_id):
    """Return all finance lines for a CLIN with computed totals."""
    clin = get_object_or_404(Clin, id=clin_id)
    lines = ContractFinanceLine.objects.filter(clin=clin).order_by('created_on')

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

        finance_line = get_object_or_404(ContractFinanceLine, id=finance_line_id)

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
    finance_line = get_object_or_404(ContractFinanceLine, id=finance_line_id)
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
