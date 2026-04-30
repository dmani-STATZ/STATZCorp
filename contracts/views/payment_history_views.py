from decimal import Decimal

from django.http import JsonResponse
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.db.models import Sum
from django.views.decorators.http import require_http_methods
import json

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, Clin, ContractFinanceLine, FinanceLinePayment, PaymentHistory


def _active_company_or_error(request):
    company = getattr(request, 'active_company', None)
    if not company:
        return None, JsonResponse({'error': 'No active company'}, status=403)
    return company, None


@conditional_login_required
@require_http_methods(["GET", "POST"])
def payment_history_api(request, entity_type, entity_id, payment_type):
    """
    API endpoint for managing payment history for Contracts, CLINs, and ContractFinanceLine
    (finance_line entity: append-only FinanceLinePayment rows).
    """
    if entity_type == 'finance_line':
        company, err = _active_company_or_error(request)
        if err:
            return err
        line = get_object_or_404(
            ContractFinanceLine.objects.select_related('clin__contract'),
            pk=entity_id,
            clin__contract__company=company,
        )
        if payment_type != 'finance_line':
            return JsonResponse({
                'error': f'Invalid payment type {payment_type} for finance line',
            }, status=400)

        if request.method == 'GET':
            qs = FinanceLinePayment.objects.filter(finance_line=line).order_by(
                '-payment_date', '-created_on'
            )
            total = qs.aggregate(t=Sum('amount'))['t'] or 0
            history_data = [{
                'payment_date': p.payment_date.isoformat(),
                'payment_amount': float(p.amount),
                'payment_info': p.note or '',
                'reference_number': '',
                'created_by': p.created_by.get_full_name() if p.created_by else 'System',
                'created_on': p.created_on.isoformat(),
            } for p in qs]
            return JsonResponse({
                'success': True,
                'history': history_data,
                'total': float(total),
                'entity_type': entity_type,
                'entity_id': entity_id,
            })

        try:
            data = json.loads(request.body)
            FinanceLinePayment.objects.create(
                finance_line=line,
                amount=Decimal(str(data['payment_amount'])),
                payment_date=data['payment_date'],
                note=(data.get('payment_info') or '')[:255] or None,
                created_by=request.user,
                modified_by=request.user,
            )
            new_total = FinanceLinePayment.objects.filter(finance_line=line).aggregate(
                t=Sum('amount')
            )['t'] or 0
            return JsonResponse({
                'success': True,
                'new_total': float(new_total),
                'payment_id': None,
                'message': 'Finance line payment recorded successfully',
            })
        except (json.JSONDecodeError, KeyError) as e:
            return JsonResponse({'error': f'Invalid request data: {str(e)}'}, status=400)
        except Exception as e:
            return JsonResponse({'error': f'Failed to record payment: {str(e)}'}, status=500)

    model_map = {
        'contract': Contract,
        'clin': Clin,
    }

    if entity_type not in model_map:
        return JsonResponse({'error': f'Invalid entity type: {entity_type}'}, status=400)

    company, err = _active_company_or_error(request)
    if err:
        return err

    model = model_map[entity_type]
    content_type = ContentType.objects.get_for_model(model)

    if entity_type == 'contract':
        entity = get_object_or_404(Contract.objects.filter(company=company), id=entity_id)
    else:
        entity = get_object_or_404(
            Clin.objects.filter(contract__company=company),
            id=entity_id,
        )

    if request.method == 'GET':
        history = PaymentHistory.objects.filter(
            content_type=content_type,
            object_id=entity_id,
            payment_type=payment_type,
        ).order_by('-payment_date', '-created_on')

        total = history.aggregate(total=Sum('payment_amount'))['total'] or 0

        history_data = [{
            'payment_date': entry.payment_date.isoformat(),
            'payment_amount': float(entry.payment_amount),
            'payment_info': entry.payment_info,
            'reference_number': entry.reference_number,
            'created_by': entry.created_by.get_full_name() if entry.created_by else 'System',
            'created_on': entry.created_on.isoformat(),
        } for entry in history]

        return JsonResponse({
            'success': True,
            'history': history_data,
            'total': float(total),
            'entity_type': entity_type,
            'entity_id': entity_id,
        })

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)

            valid_types = (
                PaymentHistory.get_contract_payment_types()
                if entity_type == 'contract'
                else PaymentHistory.get_clin_payment_types()
            )

            if payment_type not in valid_types:
                return JsonResponse({
                    'error': f'Invalid payment type {payment_type} for {entity_type}',
                }, status=400)

            payment = PaymentHistory.objects.create(
                content_type=content_type,
                object_id=entity_id,
                payment_type=payment_type,
                payment_amount=Decimal(str(data['payment_amount'])),
                payment_date=data['payment_date'],
                payment_info=data.get('payment_info', ''),
                reference_number=data.get('reference_number', ''),
                created_by=request.user,
                modified_by=request.user,
            )

            new_total = PaymentHistory.objects.filter(
                content_type=content_type,
                object_id=entity_id,
                payment_type=payment_type,
            ).aggregate(total=Sum('payment_amount'))['total'] or 0

            if entity_type == 'contract':
                contract = Contract.objects.select_related('idiq_contract', 'status').get(
                    id=entity_id, company=company
                )
                if payment_type == 'contract_value':
                    contract.contract_value = new_total
                elif payment_type == 'plan_gross':
                    contract.plan_gross = new_total
                contract.save()

            elif entity_type == 'clin':
                clin = Clin.objects.get(id=entity_id, contract__company=company)
                if payment_type == 'item_value':
                    clin.item_value = new_total
                elif payment_type == 'quote_value':
                    clin.quote_value = new_total
                elif payment_type == 'paid_amount':
                    clin.paid_amount = new_total
                elif payment_type == 'wawf_payment':
                    clin.wawf_payment = new_total
                clin.save()

            return JsonResponse({
                'success': True,
                'new_total': float(new_total),
                'payment_id': payment.id,
                'message': 'Payment history entry created successfully',
            })

        except (json.JSONDecodeError, KeyError) as e:
            return JsonResponse({'error': f'Invalid request data: {str(e)}'}, status=400)
        except Exception as e:
            return JsonResponse({'error': f'Failed to create payment history: {str(e)}'}, status=500)


@conditional_login_required
def get_entity_details(request, entity_type, entity_id):
    """Get details about an entity for the payment history popup"""
    company, err = _active_company_or_error(request)
    if err:
        return err

    if entity_type == 'finance_line':
        line = get_object_or_404(
            ContractFinanceLine.objects.select_related('clin__contract'),
            pk=entity_id,
            clin__contract__company=company,
        )
        return JsonResponse({
            'success': True,
            'entity_type': entity_type,
            'entity_id': entity_id,
            'details': {
                'number': f"{line.line_type} — CLIN {line.clin.item_number}",
                'contract_number': line.clin.contract.contract_number if line.clin.contract else None,
                'valid_payment_types': ['finance_line'],
            },
        })

    model_map = {
        'contract': Contract,
        'clin': Clin,
    }

    if entity_type not in model_map:
        return JsonResponse({'error': f'Invalid entity type: {entity_type}'}, status=400)

    model = model_map[entity_type]

    try:
        if entity_type == 'contract':
            entity = get_object_or_404(Contract.objects.filter(company=company), id=entity_id)
            details = {
                'number': entity.contract_number,
                'valid_payment_types': PaymentHistory.get_contract_payment_types(),
            }
        else:
            entity = get_object_or_404(
                Clin.objects.filter(contract__company=company),
                id=entity_id,
            )
            details = {
                'number': f"CLIN {entity.item_number}",
                'contract_number': entity.contract.contract_number if entity.contract else None,
                'valid_payment_types': PaymentHistory.get_clin_payment_types(),
            }

        return JsonResponse({
            'success': True,
            'entity_type': entity_type,
            'entity_id': entity_id,
            'details': details,
        })

    except model.DoesNotExist:
        return JsonResponse({'error': f'{entity_type.title()} not found'}, status=404)
