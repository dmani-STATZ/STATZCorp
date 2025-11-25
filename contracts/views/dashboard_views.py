from django.shortcuts import render
from django.views.generic import TemplateView
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.db.models import Q, Count, Sum, F, Value, CharField, IntegerField
from django.db.models.functions import Cast, Coalesce
from django.utils.safestring import mark_safe
from datetime import timedelta, datetime
import calendar
from django.http import Http404

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, Clin, Reminder, CanceledReason
from users.user_settings import UserSettings


def get_period_boundaries(now):
    """Return start/end datetimes for all dashboard periods."""
    this_week_start = now - timedelta(days=now.weekday())
    this_week_end = this_week_start + timedelta(days=6)
    last_week_start = this_week_start - timedelta(weeks=1)
    last_week_end = last_week_start + timedelta(days=6)

    this_month_start = now.replace(day=1)
    this_month_end = now.replace(day=calendar.monthrange(now.year, now.month)[1])

    if now.month == 1:
        last_month_start = now.replace(year=now.year-1, month=12, day=1)
        last_month_end = now.replace(year=now.year-1, month=12, day=31)
    else:
        last_month_start = now.replace(month=now.month-1, day=1)
        last_month_end = now.replace(month=now.month-1, day=calendar.monthrange(now.year, now.month-1)[1])

    current_quarter = (now.month - 1) // 3
    this_quarter_start = now.replace(month=current_quarter * 3 + 1, day=1)
    this_quarter_end = now.replace(
        month=min(12, (current_quarter + 1) * 3),
        day=calendar.monthrange(now.year, min(12, (current_quarter + 1) * 3))[1]
    )

    if current_quarter == 0:
        last_quarter_start = now.replace(year=now.year - 1, month=10, day=1)
        last_quarter_end = now.replace(year=now.year - 1, month=12, day=31)
    else:
        last_quarter_start = now.replace(month=((current_quarter - 1) * 3) + 1, day=1)
        last_quarter_month = min(12, current_quarter * 3)
        last_quarter_end = now.replace(
            month=last_quarter_month,
            day=calendar.monthrange(now.year, last_quarter_month)[1]
        )

    this_year_start = now.replace(month=1, day=1)
    this_year_end = now.replace(month=12, day=31)
    last_year_start = this_year_start.replace(year=this_year_start.year-1)
    last_year_end = last_year_start.replace(month=12, day=31)

    return {
        'this_week': (this_week_start, this_week_end),
        'last_week': (last_week_start, last_week_end),
        'this_month': (this_month_start, this_month_end),
        'last_month': (last_month_start, last_month_end),
        'this_quarter': (this_quarter_start, this_quarter_end),
        'last_quarter': (last_quarter_start, last_quarter_end),
        'this_year': (this_year_start, this_year_end),
        'last_year': (last_year_start, last_year_end),
    }


@method_decorator(conditional_login_required, name='dispatch')
class ContractLifecycleDashboardView(TemplateView):
    template_name = 'contracts/contract_lifecycle_dashboard.html'
    
    def get_contracts(self):
        # Get the last 20 contracts entered that have cancelled=False
        last_20_contracts = Contract.objects.filter(
                status__description__in=['Open']
            , company=self.request.active_company
            ).prefetch_related(
                'idiq_contract',
                'clin_set',
                'clin_set__supplier'
            ).order_by('-award_date')[:20]
        
        # Prepare the data for rendering or serialization
        contracts_data = []
        for contract in last_20_contracts:
            # Get the first CLIN with clin_type_id=1 for this contract
            first_clin = contract.clin_set.filter().first()
            
            contract_data = {
                'id': contract.id,
                'tab_num': contract.tab_num,
                'po_number': contract.po_number,
                'contract_number': contract.contract_number,
                'contract_value': contract.contract_value,
                'award_date': contract.award_date,
                'due_date': contract.due_date,
                'status': contract.status,
                'idiq_contract': contract.idiq_contract,  # Pass the entire object
            }
            
            if first_clin and first_clin.supplier:
                contract_data['supplier_name'] = first_clin.supplier.name
            else:
                contract_data['supplier_name'] = 'N/A'
            
            contracts_data.append(contract_data)

        return contracts_data
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cancel_reasons'] = CanceledReason.objects.all()
        now = timezone.now()

        # Get user's dashboard view preference
        dashboard_view = UserSettings.get_setting(
            user=self.request.user,
            name='dashboard_view_preference',
            default='card'  # Default to card view if no preference set
        )
        context['dashboard_view'] = dashboard_view

        # Get total contracts
        total_contracts = Contract.objects.filter(date_canceled__isnull=True, status__description='Open', company=self.request.active_company).count()
        context['total_contracts'] = total_contracts
        
        period_boundaries = get_period_boundaries(now)

        # Helper function to get stats for a time period
        def get_period_stats(start_date, end_date=None):
            if not end_date:
                end_date = now

            past_contracts = Contract.objects.filter(company=self.request.active_company, due_date__range=(start_date, end_date)).exclude(status__description='Cancelled')
            contracts = Contract.objects.filter(company=self.request.active_company, award_date__range=(start_date, end_date)).exclude(status__description='Cancelled')
            clins = Clin.objects.filter(company=self.request.active_company, contract__award_date__range=(start_date, end_date)).exclude(contract__status__description='Cancelled')
            
            return {
                'contracts_due': past_contracts.distinct().count(),
                'contracts_due_late': past_contracts.filter(due_date_late=True).distinct().count(),
                'contracts_due_ontime': past_contracts.filter(due_date_late=False).distinct().count(),
                'new_contract_value': contracts.aggregate(total=Sum('contract_value'))['total'] or 0,
                'new_contracts': contracts.distinct().count(),
                'date_range': mark_safe(f"{start_date.strftime('%Y/%m/%d')} to<br>{end_date.strftime('%Y/%m/%d')}"),
            }
        
        # Get stats for each time period
        periods = {
            key: get_period_stats(*period_boundaries[key])
            for key in [
                'this_week',
                'last_week',
                'this_month',
                'last_month',
                'this_quarter',
                'last_quarter',
                'this_year',
                'last_year',
            ]
        }

        context['periods'] = periods
        context['contracts'] = self.get_contracts()
        
        # Get all active contracts (not cancelled and not closed)
        active_contracts = Contract.objects.filter(
            ~Q(status__description='Cancelled') & ~Q(status__description='Closed'), company=self.request.active_company)
        
        # Contracts by stage
        context['new_contracts'] = active_contracts.filter(
            award_date__gte=timezone.now() - timedelta(days=30)
        ).count()
        
        # Contracts with CLINs that have acknowledgments pending
        contracts_with_pending_acks = Contract.objects.filter(
            clin__clinacknowledgment__po_to_supplier_bool=True,
            clin__clinacknowledgment__clin_reply_bool=False,
            company=self.request.active_company
        ).distinct().count()
        context['pending_acknowledgment'] = contracts_with_pending_acks
        
        # Contracts with CLINs that are in production (acknowledged but not shipped)
        contracts_in_production = Contract.objects.filter(
            clin__clinacknowledgment__clin_reply_bool=True,
            clin__ship_date=None,
            company=self.request.active_company
        ).distinct().count()
        context['in_production'] = contracts_in_production
        
        # Contracts with CLINs that are shipped but not paid
        contracts_shipped_not_paid = Contract.objects.filter(
            clin__ship_date__isnull=False,
            clin__paid_date=None,
            company=self.request.active_company
        ).distinct().count()
        context['shipped_not_paid'] = contracts_shipped_not_paid
        
        # Contracts with all CLINs paid
        contracts_all_paid = Contract.objects.filter(company=self.request.active_company).annotate(
            total_clins=Count('clin'),
            paid_clins=Count('clin', filter=Q(clin__paid_date__isnull=False))
        ).filter(
            total_clins=F('paid_clins'),
            total_clins__gt=0
        ).count()
        context['fully_paid'] = contracts_all_paid
        
        # Contracts with upcoming due dates
        context['due_soon'] = active_contracts.filter(
            due_date__range=[timezone.now(), timezone.now() + timedelta(days=14)]
        ).count()
        
        # Contracts that are past due
        context['past_due'] = active_contracts.filter(
            due_date__lt=timezone.now(),
            due_date_late=True
        ).count()
        
        # User's reminders
        context['pending_reminders'] = Reminder.objects.filter(
            reminder_user=self.request.user,
            reminder_completed=False,
            reminder_date__lte=timezone.now() + timedelta(days=7)
        ).order_by('reminder_date')[:5]

        # Metrics for contract lifecycle dashboard
        # Get open contracts
        open_contracts = Contract.objects.filter(
            status__description='Open',  # Using the status relation with description='Open'
            date_canceled__isnull=True,  # Ensure we exclude cancelled contracts
            company=self.request.active_company
        )

        # Count total open contracts
        open_contracts_count = open_contracts.count()

        # Find overdue contracts (due_date is in the past)
        overdue_contracts = open_contracts.filter(
            due_date__lt=timezone.now()  # Due date is less than current time
        )
        overdue_contracts_count = overdue_contracts.count()

        # Find on-time contracts (due_date is in the future or null)
        on_time_contracts = open_contracts.filter(
            Q(due_date__gte=timezone.now()) | Q(due_date__isnull=True)
        )
        on_time_contracts_count = on_time_contracts.count()

        # Calculate percentage of on-time contracts
        on_time_percentage = round((on_time_contracts_count / open_contracts_count * 100) if open_contracts_count > 0 else 0)

        # Get upcoming contracts (due within next 14 days)
        upcoming_contracts = open_contracts.filter(
            due_date__range=[timezone.now(), timezone.now() + timedelta(days=14)]
        ).order_by('due_date')
        
        upcoming_due_dates = upcoming_contracts.count()
        
        # Get buyer breakdown directly from the Buyer field for open contracts
        buyer_breakdown_qs = (
            open_contracts.annotate(
                buyer_name=Coalesce('buyer__description', Value('Unassigned'), output_field=CharField())
            )
            .values('buyer_name')
            .annotate(total=Count('id'))
            .order_by('-total', 'buyer_name')[:6]
        )
        buyer_breakdown = {row['buyer_name']: row['total'] for row in buyer_breakdown_qs}
        
        # Get active suppliers (suppliers with open contracts and CLINs with item_number < 0990)
        # First convert item_number to a numeric value for comparison
        # Get suppliers with open contracts and specific CLIN conditions
        active_suppliers = Clin.objects.filter(
            contract__status__description='Open',
            contract__date_canceled__isnull=True,
            company=self.request.active_company
        ).annotate(
            numeric_item=Cast('item_number', output_field=IntegerField())
        ).filter(
            numeric_item__lt=99  # Only include CLINs with item_number < 0990
        ).values(
            'supplier_id',
            'supplier__name'
        ).annotate(
            contract_count=Count('contract_id', distinct=True)  # distinct=True ensures each contract is counted only once
        ).order_by('-contract_count')
        
        # Count total unique suppliers
        active_supplier_count = active_suppliers.count()
        
        # Get top 5 suppliers
        top_suppliers = active_suppliers[:5]
        
        # Create metrics dictionary for template
        context['metrics'] = {
            'open_contracts': open_contracts_count,
            'overdue_contracts': overdue_contracts_count,
            'on_time_contracts': on_time_contracts_count,
            'on_time_percentage': on_time_percentage,
            'upcoming_due_dates': upcoming_due_dates,
            'upcoming_contracts': upcoming_contracts[:5],  # Limit to 5 for display
            'contract_types': buyer_breakdown,  # Renamed for template compatibility
            'total_contracts': Contract.objects.filter(date_canceled__isnull=True, company=self.request.active_company).count(),
            'active_supplier_count': active_supplier_count,
            'top_suppliers': top_suppliers
        }

        return context


@method_decorator(conditional_login_required, name='dispatch')
class DashboardMetricDetailView(TemplateView):
    template_name = 'contracts/dashboard_metric_detail.html'

    PERIOD_LABELS = {
        'this_week': 'This Week',
        'last_week': 'Last Week',
        'this_month': 'This Month',
        'last_month': 'Last Month',
        'this_quarter': 'This Quarter',
        'last_quarter': 'Last Quarter',
        'this_year': 'This Year',
        'last_year': 'Last Year',
    }

    METRIC_LABELS = {
        'contracts_due': 'Contracts Due',
        'contracts_due_late': 'Contracts Due Late',
        'contracts_due_ontime': 'Contracts Due OnTime',
        'new_contracts': 'New Contracts',
        'new_contract_value': 'New Contract Value',
    }

    SERIES_CONFIG = {
        'this_week': ('week', 26),
        'last_week': ('week', 26),
        'this_month': ('month', 24),
        'last_month': ('month', 24),
        'this_quarter': ('quarter', 16),
        'last_quarter': ('quarter', 16),
        'this_year': ('year', 10),
        'last_year': ('year', 10),
    }

    @staticmethod
    def _start_end_of_day(dt):
        return (
            dt.replace(hour=0, minute=0, second=0, microsecond=0),
            dt.replace(hour=23, minute=59, second=59, microsecond=999999),
        )

    @staticmethod
    def _month_start(dt):
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def _month_end(dt):
        last_day = calendar.monthrange(dt.year, dt.month)[1]
        return dt.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)

    @classmethod
    def _shift_months(cls, dt, months_back):
        # months_back is non-negative; shift backwards
        month_index = (dt.year * 12 + (dt.month - 1)) - months_back
        year = month_index // 12
        month = (month_index % 12) + 1
        anchor = dt.replace(year=year, month=month, day=1)
        return cls._month_start(anchor), cls._month_end(anchor)

    @classmethod
    def _shift_quarters(cls, dt, quarters_back):
        current_quarter = (dt.month - 1) // 3
        quarter_index = (dt.year * 4 + current_quarter) - quarters_back
        year = quarter_index // 4
        quarter = quarter_index % 4  # 0-based
        month = quarter * 3 + 1
        start = dt.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
        end_month = month + 2
        end_day = calendar.monthrange(year, end_month)[1]
        end = dt.replace(year=year, month=end_month, day=end_day, hour=23, minute=59, second=59, microsecond=999999)
        return start, end

    @classmethod
    def _shift_years(cls, dt, years_back):
        year = dt.year - years_back
        start = dt.replace(year=year, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = dt.replace(year=year, month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)
        return start, end

    def _build_value_series(self, period, base_start):
        """
        Build a trailing series of periods for the new_contract_value metric.
        """
        if period not in self.SERIES_CONFIG:
            return []

        granularity, count = self.SERIES_CONFIG[period]
        series = []

        for idx in range(count):
            if granularity == 'week':
                start = base_start - timedelta(weeks=idx)
                start = start.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=6)
                end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
                label = f"Week of {start.strftime('%b %d, %Y')}"
            elif granularity == 'month':
                start, end = self._shift_months(base_start, idx)
                label = start.strftime('%b %Y')
            elif granularity == 'quarter':
                start, end = self._shift_quarters(base_start, idx)
                quarter_num = ((start.month - 1) // 3) + 1
                label = f"Q{quarter_num} {start.year}"
            elif granularity == 'year':
                start, end = self._shift_years(base_start, idx)
                label = f"{start.year}"
            else:
                continue

            qs = Contract.objects.filter(
                company=self.request.active_company,
                award_date__range=(start, end),
            ).exclude(status__description='Cancelled')

            series.append({
                'label': label,
                'start': start,
                'end': end,
                'contract_count': qs.count(),
                'total_value': qs.aggregate(total=Sum('contract_value'))['total'] or 0,
            })

        # Keep most recent first
        return sorted(series, key=lambda x: x['start'], reverse=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        metric = self.request.GET.get('metric')
        period = self.request.GET.get('period')

        if metric not in self.METRIC_LABELS:
            raise Http404("Invalid metric")

        period_boundaries = get_period_boundaries(timezone.now())
        if period not in period_boundaries:
            raise Http404("Invalid period")

        start_date, end_date = period_boundaries[period]
        start_date, end_date = self._start_end_of_day(start_date)[0], self._start_end_of_day(end_date)[1]
        contracts_qs = Contract.objects.filter(company=self.request.active_company).select_related(
            'status',
            'buyer',
            'idiq_contract',
        )

        if metric == 'contracts_due':
            contracts_qs = contracts_qs.filter(due_date__range=(start_date, end_date)).exclude(status__description='Cancelled')
        elif metric == 'contracts_due_late':
            contracts_qs = contracts_qs.filter(due_date__range=(start_date, end_date), due_date_late=True).exclude(status__description='Cancelled')
        elif metric == 'contracts_due_ontime':
            contracts_qs = contracts_qs.filter(due_date__range=(start_date, end_date), due_date_late=False).exclude(status__description='Cancelled')
        elif metric in ('new_contracts', 'new_contract_value'):
            contracts_qs = contracts_qs.filter(award_date__range=(start_date, end_date)).exclude(status__description='Cancelled')

        contracts_qs = contracts_qs.order_by('-award_date', '-due_date', '-id')

        total_value = None
        if metric == 'new_contract_value':
            total_value = contracts_qs.aggregate(total=Sum('contract_value'))['total'] or 0

        value_series = None
        if metric == 'new_contract_value':
            # Use the start of the requested period as the anchor for series generation
            anchor_start = start_date
            value_series = self._build_value_series(period, anchor_start)

        context.update({
            'metric': metric,
            'metric_label': self.METRIC_LABELS[metric],
            'period': period,
            'period_label': self.PERIOD_LABELS.get(period, period),
            'start_date': start_date,
            'end_date': end_date,
            'contracts': contracts_qs,
            'contract_count': contracts_qs.count(),
            'total_value': total_value,
            'value_series': value_series,
        })
        return context
