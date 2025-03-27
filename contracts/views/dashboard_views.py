from django.shortcuts import render
from django.views.generic import TemplateView
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.db.models import Q, Count, Sum, F, Value, CharField, IntegerField
from django.db.models.functions import Cast
from django.utils.safestring import mark_safe
from datetime import timedelta, datetime
import calendar

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, Clin, Reminder


@method_decorator(conditional_login_required, name='dispatch')
class ContractLifecycleDashboardView(TemplateView):
    template_name = 'contracts/contract_lifecycle_dashboard.html'
    
    def get_contracts(self):
        # Get the last 20 contracts entered that have cancelled=False
        last_20_contracts = Contract.objects.filter(
                status__description__in=['Open']
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
        now = timezone.now()
        
        # Time periods
        this_week_start = now - timedelta(days=now.weekday())
        this_week_end = this_week_start + timedelta(days=6)
        last_week_start = this_week_start - timedelta(weeks=1)
        last_week_end = last_week_start + timedelta(days=6)

        # Calculate month boundaries
        this_month_start = now.replace(day=1)
        this_month_end = now.replace(day=calendar.monthrange(now.year, now.month)[1])
        
        # Calculate last month
        if now.month == 1:
            last_month_start = now.replace(year=now.year-1, month=12, day=1)
            last_month_end = now.replace(year=now.year-1, month=12, day=31)
        else:
            last_month_start = now.replace(month=now.month-1, day=1)
            last_month_end = now.replace(month=now.month-1, day=calendar.monthrange(now.year, now.month-1)[1])
        
        # Calculate quarter starts and ends
        current_quarter = (now.month - 1) // 3
        this_quarter_start = now.replace(month=current_quarter * 3 + 1, day=1)
        this_quarter_end = now.replace(
            month=min(12, (current_quarter + 1) * 3),
            day=calendar.monthrange(now.year, min(12, (current_quarter + 1) * 3))[1]
        )

        if current_quarter == 0:  # If we're in Q1
            last_quarter_start = now.replace(year=now.year - 1, month=10, day=1)
            last_quarter_end = now.replace(year=now.year - 1, month=12, day=31)
        else:
            last_quarter_start = now.replace(month=((current_quarter - 1) * 3) + 1, day=1)
            last_quarter_month = min(12, (current_quarter) * 3)
            last_quarter_end = now.replace(
                month=last_quarter_month,
                day=calendar.monthrange(now.year, last_quarter_month)[1]
            )

        this_year_start = now.replace(month=1, day=1)
        this_year_end = now.replace(month=12, day=31)
        last_year_start = this_year_start.replace(year=this_year_start.year-1)
        last_year_end = last_year_start.replace(month=12, day=31)

        # Helper function to get stats for a time period
        def get_period_stats(start_date, end_date=None):
            if not end_date:
                end_date = now

            past_contracts = Contract.objects.filter(due_date__range=(start_date, end_date),cancelled=False)
            contracts = Contract.objects.filter(award_date__range=(start_date, end_date),cancelled=False)
            clins = Clin.objects.filter(contract__award_date__range=(start_date, end_date),contract__cancelled=False)
            
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
            'this_week': get_period_stats(this_week_start, this_week_end),
            'last_week': get_period_stats(last_week_start, last_week_end),
            'this_month': get_period_stats(this_month_start,this_month_end),
            'last_month': get_period_stats(last_month_start, last_month_end),
            'this_quarter': get_period_stats(this_quarter_start, this_quarter_end),
            'last_quarter': get_period_stats(last_quarter_start, last_quarter_end),
            'this_year': get_period_stats(this_year_start, this_year_end),
            'last_year': get_period_stats(last_year_start, last_year_end),
        }

        context['periods'] = periods
        context['contracts'] = self.get_contracts()
        
        # Get all active contracts (not cancelled and not closed)
        active_contracts = Contract.objects.filter(
            Q(cancelled=False) & (Q(open=True) | Q(open=None)))
        
        # Contracts by stage
        context['new_contracts'] = active_contracts.filter(
            award_date__gte=timezone.now() - timedelta(days=30)
        ).count()
        
        # Contracts with CLINs that have acknowledgments pending
        contracts_with_pending_acks = Contract.objects.filter(
            clin__clinacknowledgment__po_to_supplier_bool=True,
            clin__clinacknowledgment__clin_reply_bool=False
        ).distinct().count()
        context['pending_acknowledgment'] = contracts_with_pending_acks
        
        # Contracts with CLINs that are in production (acknowledged but not shipped)
        contracts_in_production = Contract.objects.filter(
            clin__clinacknowledgment__clin_reply_bool=True,
            clin__ship_date=None
        ).distinct().count()
        context['in_production'] = contracts_in_production
        
        # Contracts with CLINs that are shipped but not paid
        contracts_shipped_not_paid = Contract.objects.filter(
            clin__ship_date__isnull=False,
            clin__paid_date=None
        ).distinct().count()
        context['shipped_not_paid'] = contracts_shipped_not_paid
        
        # Contracts with all CLINs paid
        contracts_all_paid = Contract.objects.annotate(
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
            cancelled=False              # Ensure we exclude cancelled contracts
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
        
        # Get buyer breakdown instead of contract types
        buyer_breakdown = {
            'DLA Land': open_contracts.filter(buyer_id__in=[4, 5, 8, 1048]).count(),
            'DLA Aviation': open_contracts.filter(buyer_id__in=[3, 1098, 1095]).count(),
            'DLA Maritime': open_contracts.filter(buyer_id__in=[6, 7, 1049, 1105, 1106]).count(),
            'DLA Troop Support': open_contracts.filter(buyer_id=10).count(),
        }
        
        # Calculate "Others" as the difference between total and the sum of the categorized buyers
        categorized_count = sum(buyer_breakdown.values())
        buyer_breakdown['Others'] = open_contracts_count - categorized_count
        
        # Get active suppliers (suppliers with open contracts and CLINs with item_number < 0990)
        # First convert item_number to a numeric value for comparison
        # Get suppliers with open contracts and specific CLIN conditions
        active_suppliers = Clin.objects.filter(
            contract__status__description='Open',
            contract__cancelled=False
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
            'upcoming_contracts': upcoming_contracts[:3],  # Limit to 3 for display
            'contract_types': buyer_breakdown,  # Renamed for template compatibility
            'total_contracts': Contract.objects.filter(cancelled=False).count(),
            'active_supplier_count': active_supplier_count,
            'top_suppliers': top_suppliers
        }

        return context