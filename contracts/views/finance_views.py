from collections import defaultdict
import json

from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.db.models import Q, Sum
from django.views.generic import DetailView
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.utils.decorators import method_decorator
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse
from django.urls import reverse
from ..models import Clin, ClinShipment, ClinSplit, Contract, ContractFinanceLine, ContractPackaging, PaymentHistory, ContractLevelCharge
from contracts.services.split_breakdown import build_split_breakdown_context
from .mixins import ActiveCompanyQuerysetMixin
import logging
from decimal import Decimal
from django.utils import timezone

logger = logging.getLogger(__name__)

PAYMENT_ACTIVITY_PAGE_SIZE = 50


def safe_float(value):
    """Convert a value to float, returning 0.0 if the value is None."""
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError) as e:
        logger.warning(f"Error converting value to float: {value}, Error: {str(e)}")
        return 0.0


def build_finance_audit_supplier_groups(clins_list, level_charges):
    """Group Finance Audit CLINs and level charges by supplier with subtotals."""
    main_supplier = None
    main_supplier_id = None
    for clin in clins_list:
        if clin.supplier_id:
            main_supplier = clin.supplier
            main_supplier_id = clin.supplier_id
            break

    main_key = main_supplier_id or 0
    groups = {}

    def _get_or_create_group(key, supplier_obj):
        if key not in groups:
            groups[key] = {
                'supplier': supplier_obj,
                'clins': [],
                'charges': [],
            }
        return groups[key]

    _get_or_create_group(main_key, main_supplier)
    for clin in clins_list:
        groups[main_key]['clins'].append(clin)

    for charge in level_charges:
        if charge.supplier_id is None or charge.supplier_id == main_supplier_id:
            groups[main_key]['charges'].append(charge)
        else:
            _get_or_create_group(charge.supplier_id, charge.supplier)
            groups[charge.supplier_id]['charges'].append(charge)

    supplier_groups = []
    if main_key in groups:
        supplier_groups.append(groups.pop(main_key))
    supplier_groups.extend(groups.values())

    zero = Decimal('0.00')

    def _charge_effective_amount(charge):
        if (
            charge.billed_paid_amount is not None
            and Decimal(str(charge.billed_paid_amount)) != zero
        ):
            return Decimal(str(charge.billed_paid_amount))
        return Decimal(str(charge.estimated_amount or 0))

    for group in supplier_groups:
        clin_quote = sum(
            (Decimal(str(c.quote_value or 0)) for c in group['clins']),
            zero,
        )
        clin_paid = sum(
            (Decimal(str(c.paid_amount or 0)) for c in group['clins']),
            zero,
        )
        clin_iv = sum(
            (Decimal(str(c.item_value or 0)) for c in group['clins']),
            zero,
        )
        clin_cpay = sum(
            (Decimal(str(c.wawf_payment or 0)) for c in group['clins']),
            zero,
        )
        clin_ag = sum((c.adjusted_gross for c in group['clins']), zero)
        chg_quote = sum(
            (Decimal(str(ch.estimated_amount or 0)) for ch in group['charges'] if ch.action_type == 'charge'),
            zero,
        )
        chg_paid = sum(
            (
                Decimal(str(ch.billed_paid_amount or 0))
                for ch in group['charges']
                if ch.billed_paid_amount is not None
            ),
            zero,
        )

        group['sub_quote'] = clin_quote + chg_quote
        group['sub_paid'] = clin_paid + chg_paid
        group['sub_iv'] = clin_iv
        group['sub_cpay'] = clin_cpay
        chg_ag_deduction = sum(
            (_charge_effective_amount(ch) for ch in group['charges']),
            zero,
        )
        group['sub_ag'] = clin_ag - chg_ag_deduction
        group['chg_ag_deduction'] = chg_ag_deduction

    grand_quote = sum((g['sub_quote'] for g in supplier_groups), zero)
    grand_paid = sum((g['sub_paid'] for g in supplier_groups), zero)
    grand_iv = sum((g['sub_iv'] for g in supplier_groups), zero)
    grand_cpay = sum((g['sub_cpay'] for g in supplier_groups), zero)
    grand_ag = sum((g['sub_ag'] for g in supplier_groups), zero)

    return {
        'supplier_groups': supplier_groups,
        'grand_quote': grand_quote,
        'grand_paid': grand_paid,
        'grand_iv': grand_iv,
        'grand_cpay': grand_cpay,
        'grand_ag': grand_ag,
        'main_supplier': main_supplier,
    }

@method_decorator(login_required, name='dispatch')
@method_decorator(ensure_csrf_cookie, name='dispatch')
class FinanceAuditView(ActiveCompanyQuerysetMixin, DetailView):
    model = Contract
    template_name = 'contracts/finance_audit.html'
    context_object_name = 'contract'

    def get_object(self, queryset=None):
        if self.kwargs.get('pk'):
            company = self.get_active_company()
            qs = Contract.objects.select_related(
                'buyer', 'contract_type', 'status', 'idiq_contract', 'company', 'closed_by'
            ).filter(company=company)
            return get_object_or_404(qs, pk=self.kwargs['pk'])
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['clin_split_rollup'] = []
        context['finance_lines_by_clin'] = {}
        context['shipments_by_clin'] = {}
        context['shipment_subtotals_by_clin'] = {}
        context['finance_costs_total'] = Decimal('0.00')
        context['adj_gross_contract'] = Decimal('0.00')
        context['packaging'] = None
        context['packaging_deduction'] = Decimal('0.00')
        context['packaging_share_per_company'] = {}
        context['level_charge_shares_per_company'] = {}
        context['charges_deduction'] = Decimal('0.00')
        context['level_charges'] = []
        context['level_charge_content_type_id'] = ContentType.objects.get_for_model(ContractLevelCharge).id
        context['payment_activity_rollup'] = []
        context['payment_activity_page'] = None
        context['payment_activity_total'] = 0
        context['clins'] = []
        context['contract_content_type_id'] = ContentType.objects.get_for_model(Contract).id
        context['clin_content_type_id'] = ContentType.objects.get_for_model(Clin).id
        zero = Decimal('0.00')
        context['clin_totals'] = {
            'quote_value': zero,
            'paid_amount': zero,
            'item_value': zero,
            'wawf_payment': zero,
            'adj_gross': zero,
        }
        context['supplier_groups'] = []
        context['grand_quote'] = zero
        context['grand_paid'] = zero
        context['grand_iv'] = zero
        context['grand_cpay'] = zero
        context['grand_ag'] = zero
        context['main_supplier'] = None

        try:
            if self.object:
                clins_qs = Clin.objects.filter(
                    contract=self.object
                ).select_related(
                    'supplier',
                    'special_payment_terms',
                    'nsn'
                ).order_by('item_number')

                context['clin_split_rollup'] = list(
                    ClinSplit.objects.filter(clin__contract=self.object).values('company_name').annotate(
                        total_value=Sum('split_value'),
                        total_paid=Sum('split_paid'),
                    ).order_by('company_name')
                )
                split_breakdown_context = build_split_breakdown_context(
                    self.object
                )
                context.update(split_breakdown_context)
                charges_deduction = split_breakdown_context[
                    'charges_deduction'
                ]
                level_charges = split_breakdown_context['level_charges']
                context['log_split_paid_url'] = reverse(
                    'contracts:log_split_paid',
                    kwargs={'contract_pk': self.object.pk},
                )

                finance_lines_qs = ContractFinanceLine.objects.filter(
                    clin__contract=self.object,
                    partial__isnull=True,
                ).select_related('clin').annotate(
                    amount_paid_sum=Sum('payments__amount')
                ).order_by('clin_id', 'id')

                by_clin = defaultdict(list)
                for line in finance_lines_qs:
                    paid_sum = line.amount_paid_sum
                    if paid_sum is None:
                        paid_sum = Decimal('0.00')
                    line.display_paid_sum = paid_sum
                    line.display_remaining = (line.amount_billed or Decimal('0.00')) - paid_sum
                    by_clin[line.clin_id].append(line)

                finance_costs_total = (
                    ContractFinanceLine.objects.filter(clin__contract=self.object).aggregate(
                        t=Sum('amount_billed')
                    )['t']
                    or Decimal('0.00')
                )

                context['finance_lines_by_clin'] = dict(by_clin)
                context['finance_costs_total'] = finance_costs_total

                shipments_qs = ClinShipment.objects.filter(
                    clin__contract=self.object
                ).select_related('clin').order_by('clin_id', 'ship_date', 'created_on')

                shipments_by_clin = {}
                for shipment in shipments_qs:
                    shipments_by_clin.setdefault(shipment.clin_id, []).append(shipment)

                shipment_subtotals_by_clin = {}
                for clin_id, shipments in shipments_by_clin.items():
                    shipment_subtotals_by_clin[clin_id] = {
                        'quote_value': sum(Decimal(str(s.quote_value or 0)) for s in shipments),
                        'paid_amount': sum(Decimal(str(s.paid_amount or 0)) for s in shipments),
                        'item_value': sum(Decimal(str(s.item_value or 0)) for s in shipments),
                        'wawf_payment': sum(Decimal(str(s.wawf_payment or 0)) for s in shipments),
                    }

                context['shipments_by_clin'] = shipments_by_clin
                context['shipment_subtotals_by_clin'] = shipment_subtotals_by_clin

                ct_contract = ContentType.objects.get_for_model(Contract)
                ct_clin = ContentType.objects.get_for_model(Clin)
                clin_ids = list(clins_qs.values_list('id', flat=True))
                clin_item_by_id = dict(clins_qs.values_list('id', 'item_number'))

                ph_base = PaymentHistory.objects.filter(
                    Q(content_type=ct_contract, object_id=self.object.id)
                    | Q(content_type=ct_clin, object_id__in=clin_ids)
                ).order_by('-payment_date', '-created_on')

                total_count = ph_base.count()
                paginator = Paginator(ph_base, PAYMENT_ACTIVITY_PAGE_SIZE)
                raw_page = self.request.GET.get('pa_page', '1')
                page_obj = None
                if paginator.num_pages > 0:
                    try:
                        page_obj = paginator.page(raw_page)
                    except PageNotAnInteger:
                        page_obj = paginator.page(1)
                    except EmptyPage:
                        page_obj = paginator.page(paginator.num_pages)

                payment_activity_rollup = []
                if page_obj is not None:
                    for entry in page_obj.object_list:
                        if entry.content_type_id == ct_contract.id:
                            entity_label = 'Contract'
                            entity_type = 'contract'
                        else:
                            item_no = clin_item_by_id.get(entry.object_id, '')
                            entity_label = f'CLIN {item_no}' if item_no != '' else f'CLIN {entry.object_id}'
                            entity_type = 'clin'
                        payment_activity_rollup.append({
                            'entity_label': entity_label,
                            'field_label': entry.get_payment_type_display(),
                            'amount': entry.payment_amount,
                            'payment_date': entry.payment_date,
                            'note_text': entry.payment_info or '',
                            'entity_type': entity_type,
                            'entity_id': entry.object_id,
                            'payment_type': entry.payment_type,
                            'current_value': float(entry.payment_amount),
                        })

                context['payment_activity_rollup'] = payment_activity_rollup
                context['payment_activity_page'] = page_obj
                context['payment_activity_total'] = total_count

                clins_list = list(clins_qs)
                for clin in clins_list:
                    flist = context['finance_lines_by_clin'].get(clin.id, [])
                    clin.finance_lines_for_audit = flist
                    clin.finance_billed_sum = sum(
                        (l.amount_billed for l in flist),
                        Decimal('0.00'),
                    )
                    clin.needs_unit_price = (
                        clin.unit_price is None or clin.price_per_unit is None
                    )
                context['clins'] = clins_list
                clin_adj_gross_sum = sum(
                    (c.adjusted_gross for c in clins_list),
                    Decimal('0.00'),
                )
                context['clin_totals'] = {
                    'quote_value': sum(
                        (Decimal(str(c.quote_value or 0)) for c in clins_list),
                        Decimal('0.00'),
                    ),
                    'paid_amount': sum(
                        (Decimal(str(c.paid_amount or 0)) for c in clins_list),
                        Decimal('0.00'),
                    ),
                    'item_value': sum(
                        (Decimal(str(c.item_value or 0)) for c in clins_list),
                        Decimal('0.00'),
                    ),
                    'wawf_payment': sum(
                        (Decimal(str(c.wawf_payment or 0)) for c in clins_list),
                        Decimal('0.00'),
                    ),
                    'adj_gross': clin_adj_gross_sum,
                }
                context['adj_gross_contract'] = clin_adj_gross_sum - context['packaging_deduction'] - charges_deduction

                # Contract-level CLIN sum comparison
                clin_item_value_sum = context['clin_totals']['item_value']
                contract_value = Decimal(str(self.object.contract_value or 0))
                context['clin_item_value_sum'] = clin_item_value_sum
                context['contract_value_delta'] = clin_item_value_sum - contract_value
                context['contract_value_balanced'] = abs(
                    clin_item_value_sum - contract_value
                ) <= Decimal('0.01')

                # Per-CLIN shipment sum comparison
                for clin in clins_list:
                    subtotals = shipment_subtotals_by_clin.get(clin.id, {})
                    clin.shipment_item_value_sum = subtotals.get(
                        'item_value', Decimal('0.00')
                    )
                    clin.has_shipments = clin.id in shipments_by_clin
                    clin_item_val = Decimal(str(clin.item_value or 0))
                    clin.shipment_item_value_delta = (
                        clin.shipment_item_value_sum - clin_item_val
                    )
                    clin.shipment_item_value_balanced = (
                        not clin.has_shipments
                        or abs(clin.shipment_item_value_delta) <= Decimal('0.01')
                    )

                grouped = build_finance_audit_supplier_groups(
                    clins_list, level_charges
                )
                context.update(grouped)

        except Exception as e:
            logger.error(f"Error in FinanceAuditView: {str(e)}")
            messages.error(self.request, 'An error occurred while loading the page.')

        return context


@login_required
def finance_audit_summary_api(request, contract_id):
    try:
        company = getattr(request, 'active_company', None)
        if not company:
            return JsonResponse({'error': 'No active company'}, status=403)

        contract = get_object_or_404(Contract, id=contract_id, company_id=company)

        finance_costs_total = (
            ContractFinanceLine.objects.filter(clin__contract=contract).aggregate(
                t=Sum('amount_billed')
            )['t']
            or Decimal('0.00')
        )

        packaging_deduction = Decimal('0.00')
        try:
            pkg = contract.packaging
            if pkg.amount_paid is not None and Decimal(str(pkg.amount_paid)) != Decimal('0'):
                packaging_deduction = Decimal(str(pkg.amount_paid))
            elif pkg.quote_amount is not None and Decimal(str(pkg.quote_amount)) != Decimal('0'):
                packaging_deduction = Decimal(str(pkg.quote_amount))
        except ContractPackaging.DoesNotExist:
            pass

        charges_deduction = Decimal('0.00')
        level_charges = list(
            contract.level_charges.select_related('supplier').order_by('id')
        )
        for charge in level_charges:
            if charge.billed_paid_amount is not None and Decimal(str(charge.billed_paid_amount)) != Decimal('0'):
                charges_deduction += Decimal(str(charge.billed_paid_amount))
            else:
                charges_deduction += Decimal(str(charge.estimated_amount))

        clins_list = list(Clin.objects.filter(contract=contract))
        clin_adj_gross_sum = sum(
            (c.adjusted_gross for c in clins_list),
            Decimal('0.00'),
        )
        clin_totals = {
            'quote_value': sum(
                (Decimal(str(c.quote_value or 0)) for c in clins_list),
                Decimal('0.00'),
            ),
            'paid_amount': sum(
                (Decimal(str(c.paid_amount or 0)) for c in clins_list),
                Decimal('0.00'),
            ),
            'item_value': sum(
                (Decimal(str(c.item_value or 0)) for c in clins_list),
                Decimal('0.00'),
            ),
            'wawf_payment': sum(
                (Decimal(str(c.wawf_payment or 0)) for c in clins_list),
                Decimal('0.00'),
            ),
            'adj_gross': clin_adj_gross_sum,
        }
        adj_gross_contract = clin_adj_gross_sum - packaging_deduction - charges_deduction

        clin_item_value_sum = clin_totals['item_value']
        contract_value = Decimal(str(contract.contract_value or 0))
        contract_value_delta = clin_item_value_sum - contract_value
        contract_value_balanced = abs(contract_value_delta) <= Decimal('0.01')

        grouped = build_finance_audit_supplier_groups(clins_list, level_charges)

        ct_contract = ContentType.objects.get_for_model(Contract)
        ct_clin = ContentType.objects.get_for_model(Clin)
        clin_ids = list(Clin.objects.filter(contract=contract).values_list('id', flat=True))

        ph_base = PaymentHistory.objects.filter(
            Q(content_type=ct_contract, object_id=contract.id)
            | Q(content_type=ct_clin, object_id__in=clin_ids)
        ).order_by('-payment_date', '-created_on')

        total_count = ph_base.count()

        return JsonResponse({
            'finance_costs_total': str(finance_costs_total),
            'adj_gross_contract': str(adj_gross_contract),
            'clin_totals': {
                'quote_value': str(clin_totals['quote_value']),
                'paid_amount': str(clin_totals['paid_amount']),
                'item_value': str(clin_totals['item_value']),
                'wawf_payment': str(clin_totals['wawf_payment']),
                'adj_gross': str(clin_totals['adj_gross']),
            },
            'clin_item_value_sum': str(clin_item_value_sum),
            'contract_value_delta': str(contract_value_delta),
            'contract_value_balanced': contract_value_balanced,
            'payment_activity_total': total_count,
            'charges_deduction': str(charges_deduction),
            'grand_quote': str(grouped['grand_quote']),
            'grand_paid': str(grouped['grand_paid']),
            'grand_iv': str(grouped['grand_iv']),
            'grand_cpay': str(grouped['grand_cpay']),
            'grand_ag': str(grouped['grand_ag']),
        })
    except Exception as e:
        logger.error(f"Error in finance_audit_summary_api: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def finance_audit_clin_api(request, contract_id, clin_id):
    try:
        company = getattr(request, 'active_company', None)
        if not company:
            return JsonResponse({'error': 'No active company'}, status=403)

        contract = get_object_or_404(Contract, id=contract_id, company_id=company)
        clin = get_object_or_404(Clin, id=clin_id, contract=contract)

        shipments_qs = ClinShipment.objects.filter(clin=clin).order_by('ship_date', 'created_on')
        shipment_subtotals = {
            'quote_value': sum(Decimal(str(s.quote_value or 0)) for s in shipments_qs),
            'paid_amount': sum(Decimal(str(s.paid_amount or 0)) for s in shipments_qs),
            'item_value': sum(Decimal(str(s.item_value or 0)) for s in shipments_qs),
            'wawf_payment': sum(Decimal(str(s.wawf_payment or 0)) for s in shipments_qs),
        }

        has_shipments = shipments_qs.exists()
        clin_item_val = Decimal(str(clin.item_value or 0))
        shipment_item_value_delta = shipment_subtotals['item_value'] - clin_item_val
        shipment_item_value_balanced = (
            not has_shipments
            or abs(shipment_item_value_delta) <= Decimal('0.01')
        )

        finance_lines_qs = ContractFinanceLine.objects.filter(
            clin=clin,
            partial__isnull=True,
        ).annotate(amount_paid_sum=Sum('payments__amount'))

        finance_billed_sum = sum(
            (l.amount_billed for l in finance_lines_qs),
            Decimal('0.00'),
        )

        return JsonResponse({
            'clin_id': clin.id,
            'quote_value': str(clin.quote_value or 0),
            'paid_amount': str(clin.paid_amount or 0),
            'item_value': str(clin.item_value or 0),
            'wawf_payment': str(clin.wawf_payment or 0),
            'adjusted_gross': str(clin.adjusted_gross),
            'has_shipments': has_shipments,
            'needs_unit_price': (
                clin.unit_price is None or clin.price_per_unit is None
            ),
            'shipment_item_value_sum': str(shipment_subtotals['item_value']),
            'shipment_item_value_delta': str(shipment_item_value_delta),
            'shipment_item_value_balanced': shipment_item_value_balanced,
            'finance_billed_sum': str(finance_billed_sum),
        })
    except Exception as e:
        logger.error(f"Error in finance_audit_clin_api: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def update_contract_level_charge(request, charge_id):
    company = getattr(request, 'active_company', None)
    if not company:
        return JsonResponse({'success': False, 'error': 'No active company'}, status=403)

    charge = get_object_or_404(
        ContractLevelCharge.objects.select_related('contract'),
        id=charge_id,
        contract__company=company
    )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)

    field = data.get('field')
    if field != 'billed_paid_amount':
        return JsonResponse({'success': False, 'error': 'Only billed_paid_amount field can be updated.'}, status=400)

    value_raw = data.get('value')
    if value_raw in (None, '', 'null'):
        value = None
    else:
        try:
            value = Decimal(str(value_raw))
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'error': 'Invalid Decimal value format.'}, status=400)

    try:
        with transaction.atomic():
            charge.billed_paid_amount = value
            charge.modified_by = request.user
            charge.save()

        billed_paid_amount_str = str(charge.billed_paid_amount) if charge.billed_paid_amount is not None else None
        effective_amount_str = str(charge.effective_amount)
        variance_str = str(charge.variance) if charge.variance is not None else None

        return JsonResponse({
            'success': True,
            'billed_paid_amount': billed_paid_amount_str,
            'effective_amount': effective_amount_str,
            'variance': variance_str
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)