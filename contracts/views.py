from django.shortcuts import render
from django.views.generic import TemplateView
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
from .models import Contract, Clin

# Create your views here.

class ContractsDashboardView(TemplateView):
    template_name = 'contracts/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        
        # Time periods
        this_week_start = now - timedelta(days=now.weekday())
        last_week_start = this_week_start - timedelta(weeks=1)
        this_month_start = now.replace(day=1)
        last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)
        this_quarter_start = now.replace(day=1, month=((now.month-1)//3)*3 + 1)
        last_quarter_start = (this_quarter_start - timedelta(days=1)).replace(day=1, month=((now.month-4)//3)*3 + 1)
        this_year_start = now.replace(month=1, day=1)
        last_year_start = this_year_start.replace(year=this_year_start.year-1)

        # Helper function to get stats for a time period
        def get_period_stats(start_date, end_date=None):
            if not end_date:
                end_date = now

            contracts = Contract.objects.filter(award_date__range=(start_date, end_date))
            clins = Clin.objects.filter(contract__award_date__range=(start_date, end_date))
            
            return {
                'contracts_due': contracts.filter(due_date__range=(start_date, end_date)).count(),
                'contracts_due_late': contracts.filter(due_date_late=True, due_date__range=(start_date, end_date)).count(),
                'contracts_due_ontime': contracts.filter(due_date_late=False, due_date__range=(start_date, end_date)).count(),
                'new_contract_value': clins.aggregate(total=Sum('clin_finance__contract_value'))['total'] or 0,
                'new_contracts': contracts.count(),
            }

        # Get stats for each time period
        periods = {
            'this_week': get_period_stats(this_week_start),
            'last_week': get_period_stats(last_week_start, this_week_start),
            'this_month': get_period_stats(this_month_start),
            'last_month': get_period_stats(last_month_start, this_month_start),
            'this_quarter': get_period_stats(this_quarter_start),
            'last_quarter': get_period_stats(last_quarter_start, this_quarter_start),
            'this_year': get_period_stats(this_year_start),
            'last_year': get_period_stats(last_year_start, this_year_start),
        }

        context['periods'] = periods
        return context
