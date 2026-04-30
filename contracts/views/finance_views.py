from collections import defaultdict

from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db.models import Q, Sum
from django.views.generic import DetailView
from django.utils.decorators import method_decorator
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from ..models import Clin, ClinSplit, Contract, ContractFinanceLine, PaymentHistory
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
        context['finance_costs_total'] = Decimal('0.00')
        context['adj_gross_contract'] = Decimal('0.00')
        context['payment_notes_rollup'] = []
        context['clins'] = []

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

                finance_lines_qs = ContractFinanceLine.objects.filter(
                    clin__contract=self.object
                ).select_related('clin').annotate(
                    amount_paid_sum=Sum('payments__amount')
                ).order_by('clin_id', 'id')

                by_clin = defaultdict(list)
                finance_costs_total = Decimal('0.00')
                for line in finance_lines_qs:
                    paid_sum = line.amount_paid_sum
                    if paid_sum is None:
                        paid_sum = Decimal('0.00')
                    line.display_paid_sum = paid_sum
                    line.display_remaining = (line.amount_billed or Decimal('0.00')) - paid_sum
                    by_clin[line.clin_id].append(line)
                    finance_costs_total += line.amount_billed or Decimal('0.00')

                context['finance_lines_by_clin'] = dict(by_clin)
                context['finance_costs_total'] = finance_costs_total

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

        except Exception as e:
            logger.error(f"Error in FinanceAuditView: {str(e)}")
            messages.error(self.request, 'An error occurred while loading the page.')

        return context