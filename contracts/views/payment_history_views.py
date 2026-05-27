from decimal import Decimal

from django.http import JsonResponse
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.db.models import Sum
from django.views.decorators.http import require_http_methods
import json

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, Clin, ClinShipment, ContractFinanceLine, ContractPackaging, FinanceLinePayment, PaymentHistory
from .shipment_views import _recompute_clin_payment_rollup


def _active_company_or_error(request):
    company = getattr(request, 'active_company', None)
    if not company:
        return None, JsonResponse({'error': 'No active company'}, status=403)
    return company, None


def _partial_payment_rollup_mapping(payment_type):
    """Map partial shipment payment types to parent CLIN types, or None if no rollup."""
    if payment_type == 'partial_wawf_payment':
        return 'wawf_payment', 'wawf_payment'
    if payment_type == 'partial_paid_amount':
        return 'paid_amount', 'paid_amount'
    return None


def _verify_payment_history_company_access(entry, company):
    """Return (entity_type, None) on success or (None, JsonResponse error)."""
    entity_type = entry.entity_type
    object_id = entry.object_id

    if entity_type == 'contract':
        try:
            contract = Contract.objects.get(id=object_id)
        except Contract.DoesNotExist:
            return None, JsonResponse({'error': 'Contract not found'}, status=404)
        if contract.company_id != company.id:
            return None, JsonResponse({'error': 'Permission denied'}, status=403)
    elif entity_type == 'clin':
        try:
            clin = Clin.objects.select_related('contract').get(id=object_id)
        except Clin.DoesNotExist:
            return None, JsonResponse({'error': 'CLIN not found'}, status=404)
        if clin.contract.company_id != company.id:
            return None, JsonResponse({'error': 'Permission denied'}, status=403)
    elif entity_type == 'clinshipment':
        try:
            shipment = ClinShipment.objects.select_related('clin__contract').get(id=object_id)
        except ClinShipment.DoesNotExist:
            return None, JsonResponse({'error': 'Shipment not found'}, status=404)
        if shipment.clin.contract.company_id != company.id:
            return None, JsonResponse({'error': 'Permission denied'}, status=403)
    elif entity_type == 'contractpackaging':
        try:
            pkg = ContractPackaging.objects.select_related('contract').get(id=object_id)
        except ContractPackaging.DoesNotExist:
            return None, JsonResponse({'error': 'Packaging not found'}, status=404)
        if pkg.contract.company_id != company.id:
            return None, JsonResponse({'error': 'Permission denied'}, status=403)
    else:
        return None, JsonResponse({'error': 'Unsupported entity type'}, status=400)

    return entity_type, None


def _sync_entity_total_after_history_change(
    entity_type, object_id, payment_type, content_type, company, user
):
    """Recompute ledger sum and write parent model field. Returns new_total as float."""
    new_total = PaymentHistory.objects.filter(
        content_type=content_type,
        object_id=object_id,
        payment_type=payment_type,
    ).aggregate(total=Sum('payment_amount'))['total'] or Decimal('0.00')

    if entity_type == 'contract':
        contract = Contract.objects.select_related('idiq_contract', 'status').get(
            id=object_id, company=company
        )
        if payment_type == 'contract_value':
            contract.contract_value = new_total
        elif payment_type == 'plan_gross':
            contract.plan_gross = new_total
        contract.save()

    elif entity_type == 'clin':
        clin = Clin.objects.get(id=object_id, contract__company=company)
        if payment_type == 'item_value':
            clin.item_value = new_total
        elif payment_type == 'quote_value':
            clin.quote_value = new_total
        elif payment_type == 'paid_amount':
            clin.paid_amount = new_total
        elif payment_type == 'wawf_payment':
            clin.wawf_payment = new_total
        clin.save()

    elif entity_type == 'clinshipment':
        shipment = ClinShipment.objects.select_related('clin').get(
            id=object_id,
            clin__contract__company=company,
        )
        if payment_type == 'partial_item_value':
            shipment.item_value = new_total
        elif payment_type == 'partial_quote_value':
            shipment.quote_value = new_total
        elif payment_type == 'partial_paid_amount':
            shipment.paid_amount = new_total
        elif payment_type == 'partial_wawf_payment':
            shipment.wawf_payment = new_total
        shipment.save()
        if _partial_payment_rollup_mapping(payment_type):
            _recompute_clin_payment_rollup(shipment.clin, user)

    elif entity_type == 'contractpackaging':
        pkg = ContractPackaging.objects.get(
            id=object_id, contract__company=company
        )
        if payment_type == 'packaging_quote':
            pkg.quote_amount = new_total
            update_field = 'quote_amount'
        elif payment_type == 'packaging_paid':
            pkg.amount_paid = new_total
            update_field = 'amount_paid'
        else:
            update_field = None
        if update_field:
            pkg.modified_by = user
            pkg.save(update_fields=[update_field, 'modified_by', 'modified_on'])

    return float(new_total)


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
        'clinshipment': ClinShipment,
        'contract_packaging': ContractPackaging,
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
    elif entity_type == 'clinshipment':
        entity = get_object_or_404(
            ClinShipment.objects.filter(clin__contract__company=company),
            id=entity_id,
        )
    elif entity_type == 'contract_packaging':
        entity = get_object_or_404(
            ContractPackaging.objects.filter(contract__company=company),
            id=entity_id,
        )
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
            'id': entry.id,
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

            if entity_type == 'contract':
                valid_types = PaymentHistory.get_contract_payment_types()
            elif entity_type == 'clin':
                valid_types = PaymentHistory.get_clin_payment_types()
            elif entity_type == 'clinshipment':
                valid_types = PaymentHistory.get_clinshipment_payment_types()
            elif entity_type == 'contract_packaging':
                valid_types = PaymentHistory.get_contract_packaging_payment_types()
            else:
                valid_types = []

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
                if payment_type in ('paid_amount', 'wawf_payment') and clin.shipments.exists():
                    return JsonResponse(
                        {
                            'success': False,
                            'error': (
                                'Paid / Customer Pay for this CLIN is calculated from '
                                'its shipments. Edit the shipment instead.'
                            ),
                        },
                        status=400,
                    )
                if payment_type == 'item_value':
                    clin.item_value = new_total
                elif payment_type == 'quote_value':
                    clin.quote_value = new_total
                elif payment_type == 'paid_amount':
                    clin.paid_amount = new_total
                elif payment_type == 'wawf_payment':
                    clin.wawf_payment = new_total
                clin.save()
            elif entity_type == 'clinshipment':
                shipment = ClinShipment.objects.select_related('clin').get(
                    id=entity_id,
                    clin__contract__company=company
                )
                if payment_type == 'partial_item_value':
                    shipment.item_value = new_total
                elif payment_type == 'partial_quote_value':
                    shipment.quote_value = new_total
                elif payment_type == 'partial_paid_amount':
                    shipment.paid_amount = new_total
                elif payment_type == 'partial_wawf_payment':
                    shipment.wawf_payment = new_total
                shipment.save()
                if _partial_payment_rollup_mapping(payment_type):
                    _recompute_clin_payment_rollup(shipment.clin, request.user)
            elif entity_type == 'contract_packaging':
                pkg = ContractPackaging.objects.get(
                    id=entity_id, contract__company=company
                )
                if payment_type == 'packaging_quote':
                    pkg.quote_amount = new_total
                    update_field = 'quote_amount'
                else:
                    pkg.amount_paid = new_total
                    update_field = 'amount_paid'
                pkg.modified_by = request.user
                pkg.save(update_fields=[update_field, 'modified_by', 'modified_on'])

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
@require_http_methods(["DELETE"])
def delete_payment_history_entry(request, payment_id):
    company, err = _active_company_or_error(request)
    if err:
        return err

    try:
        entry = PaymentHistory.objects.select_related('content_type').get(pk=payment_id)
    except PaymentHistory.DoesNotExist:
        return JsonResponse({'error': 'Payment history entry not found'}, status=404)

    entity_type, err = _verify_payment_history_company_access(entry, company)
    if err:
        return err

    object_id = entry.object_id
    payment_type = entry.payment_type
    content_type = entry.content_type

    try:
        entry.delete()
        new_total = _sync_entity_total_after_history_change(
            entity_type,
            object_id,
            payment_type,
            content_type,
            company,
            request.user,
        )
        return JsonResponse({
            'success': True,
            'new_total': new_total,
            'payment_id': payment_id,
        })
    except Exception as e:
        return JsonResponse({'error': f'Failed to delete payment history: {str(e)}'}, status=500)


@conditional_login_required
@require_http_methods(["PATCH"])
def update_payment_history_entry(request, payment_id):
    """Update an existing PaymentHistory row and resync parent totals."""
    company, err = _active_company_or_error(request)
    if err:
        return err

    try:
        entry = PaymentHistory.objects.select_related('content_type').get(pk=payment_id)
    except PaymentHistory.DoesNotExist:
        return JsonResponse({'error': 'Payment history entry not found'}, status=404)

    entity_type, err = _verify_payment_history_company_access(entry, company)
    if err:
        return err

    if entity_type == 'clin' and entry.payment_type in ('paid_amount', 'wawf_payment'):
        clin = Clin.objects.get(id=entry.object_id, contract__company=company)
        if clin.shipments.exists():
            return JsonResponse(
                {
                    'success': False,
                    'error': (
                        'Paid / Customer Pay for this CLIN is calculated from '
                        'its shipments. Edit the shipment ledger instead.'
                    ),
                },
                status=400,
            )

    try:
        data = json.loads(request.body)
        entry.payment_amount = Decimal(str(data['payment_amount']))
        entry.payment_date = data['payment_date']
        entry.payment_info = data.get('payment_info', '') or ''
        entry.reference_number = data.get('reference_number', '') or ''
        entry.modified_by = request.user
        entry.save()

        new_total = _sync_entity_total_after_history_change(
            entity_type,
            entry.object_id,
            entry.payment_type,
            entry.content_type,
            company,
            request.user,
        )
        return JsonResponse({
            'success': True,
            'new_total': new_total,
            'payment_id': payment_id,
            'message': 'Payment history entry updated successfully',
        })
    except (json.JSONDecodeError, KeyError) as e:
        return JsonResponse({'error': f'Invalid request data: {str(e)}'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Failed to update payment history: {str(e)}'}, status=500)


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
        'clinshipment': ClinShipment,
        'contract_packaging': ContractPackaging,
    }

    if entity_type not in model_map and entity_type != 'finance_line':
        return JsonResponse({'error': f'Invalid entity type: {entity_type}'}, status=400)

    model = model_map[entity_type]

    try:
        if entity_type == 'contract':
            entity = get_object_or_404(Contract.objects.filter(company=company), id=entity_id)
            details = {
                'number': entity.contract_number,
                'valid_payment_types': PaymentHistory.get_contract_payment_types(),
            }
        elif entity_type == 'clin':
            entity = get_object_or_404(
                Clin.objects.filter(contract__company=company),
                id=entity_id,
            )
            details = {
                'number': f"CLIN {entity.item_number}",
                'contract_number': entity.contract.contract_number if entity.contract else None,
                'valid_payment_types': PaymentHistory.get_clin_payment_types(),
            }
        elif entity_type == 'clinshipment':
            shipment = get_object_or_404(
                ClinShipment.objects.select_related('clin__contract'),
                pk=entity_id,
                clin__contract__company=company,
            )
            details = {
                'number': f"Partial — CLIN {shipment.clin.item_number}",
                'contract_number': shipment.clin.contract.contract_number
                    if shipment.clin.contract else None,
                'valid_payment_types': PaymentHistory.get_clinshipment_payment_types(),
            }
        elif entity_type == 'contract_packaging':
            pkg = get_object_or_404(
                ContractPackaging.objects.select_related('packhouse', 'contract'),
                pk=entity_id,
                contract__company=company,
            )
            details = {
                'number': pkg.packhouse.name if pkg.packhouse else '—',
                'contract_number': pkg.contract.contract_number,
                'valid_payment_types': PaymentHistory.get_contract_packaging_payment_types(),
            }
        else:
            return JsonResponse({'error': f'Invalid entity type: {entity_type}'}, status=400)

        return JsonResponse({
            'success': True,
            'entity_type': entity_type,
            'entity_id': entity_id,
            'details': details,
        })

    except model.DoesNotExist:
        return JsonResponse({'error': f'{entity_type.title()} not found'}, status=404)
