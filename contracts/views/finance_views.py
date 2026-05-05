from collections import defaultdict

from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db.models import Q, Sum
from django.views.generic import DetailView
from django.utils.decorators import method_decorator
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from ..models import Clin, ClinShipment, ClinSplit, Contract, ContractFinanceLine, PaymentHistory
from .mixins import ActiveCompanyQuerysetMixin
import logging
from decimal import Decimal
from django.utils import timezone

logger = logging.getLogger(__name__)

def safe_float(value):
    """Convert a value to float, returning 0.0 if the value is None."""
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError) as e:
        logger.warning(f"Error converting value to float: {value}, Error: {str(e)}")
        return 0.0

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
                'buyer', 'contract_type', 'status', 'idiq_contract', 'company'
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
        context['payment_notes_rollup'] = []
        context['clins'] = []
        zero = Decimal('0.00')
        context['clin_totals'] = {
            'quote_value': zero,
            'paid_amount': zero,
            'item_value': zero,
            'wawf_payment': zero,
            'adj_gross': zero,
        }

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
                # Per-CLIN split breakdown for Finance Audit accordion.
                clin_splits_by_company = {}
                for split in ClinSplit.objects.filter(
                    clin__contract=self.object
                ).select_related('clin').order_by('company_name', 'clin__item_number'):
                    cname = split.company_name
                    if cname not in clin_splits_by_company:
                        clin_splits_by_company[cname] = []
                    clin_splits_by_company[cname].append({
                        'item_number': split.clin.item_number,
                        'split_value': split.split_value,
                        'split_paid': split.split_paid,
                        'percentage': split.percentage,
                    })
                context['clin_splits_by_company'] = clin_splits_by_company

                # Use the first non-null percentage found per company for summary display.
                company_percentages = {}
                for cname, rows in clin_splits_by_company.items():
                    for row in rows:
                        if row['percentage'] is not None:
                            company_percentages[cname] = row['percentage']
                            break
                context['company_percentages'] = company_percentages

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

                plan = self.object.plan_gross
                plan_dec = plan if plan is not None else Decimal('0.00')
                context['adj_gross_contract'] = plan_dec - finance_costs_total

                ct_contract = ContentType.objects.get_for_model(Contract)
                ct_clin = ContentType.objects.get_for_model(Clin)
                clin_ids = list(clins_qs.values_list('id', flat=True))
                clin_item_by_id = dict(clins_qs.values_list('id', 'item_number'))

                ph_base = PaymentHistory.objects.filter(
                    Q(content_type=ct_contract, object_id=self.object.id)
                    | Q(content_type=ct_clin, object_id__in=clin_ids)
                ).exclude(
                    payment_info__isnull=True
                ).exclude(
                    payment_info=''
                ).order_by('-payment_date', '-created_on')

                payment_notes_rollup = []
                for entry in ph_base:
                    if entry.content_type_id == ct_contract.id:
                        entity_label = 'Contract'
                    else:
                        item_no = clin_item_by_id.get(entry.object_id, '')
                        entity_label = f'CLIN {item_no}' if item_no != '' else f'CLIN {entry.object_id}'
                    payment_notes_rollup.append({
                        'field_label': entry.get_payment_type_display(),
                        'amount': entry.payment_amount,
                        'note_text': entry.payment_info,
                        'entity_label': entity_label,
                    })
                context['payment_notes_rollup'] = payment_notes_rollup

                clins_list = list(clins_qs)
                for clin in clins_list:
                    flist = context['finance_lines_by_clin'].get(clin.id, [])
                    clin.finance_lines_for_audit = flist
                    clin.finance_billed_sum = sum(
                        (l.amount_billed for l in flist),
                        Decimal('0.00'),
                    )
                context['clins'] = clins_list
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
                    'adj_gross': sum(
                        (c.adjusted_gross for c in clins_list),
                        Decimal('0.00'),
                    ),
                }

        except Exception as e:
            logger.error(f"Error in FinanceAuditView: {str(e)}")
            messages.error(self.request, 'An error occurred while loading the page.')

        return context