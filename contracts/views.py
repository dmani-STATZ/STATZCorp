from django.shortcuts import render, get_object_or_404
from STATZWeb.decorators import conditional_login_required
from django.views.generic import TemplateView, DetailView, UpdateView
from django.db.models import Count, Sum, Q
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.http import JsonResponse
from datetime import timedelta, datetime
import calendar
from .models import Contract, Clin, ClinFinance, Supplier, Nsn, ClinAcknowledgment
from django.urls import reverse_lazy
from .forms import NsnForm, SupplierForm
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
import json

# Create your views here.

@method_decorator(conditional_login_required, name='dispatch')
class ContractsDashboardView(TemplateView):
    template_name = 'contracts/dashboard.html'

    def get_contracts(self):
        # Get the last 20 contracts entered that have cancelled=False
        last_20_contracts = Contract.objects.filter(
                cancelled=False
            ).prefetch_related(
                'clin_set',
                'clin_set__clin_finance',
                'clin_set__supplier'
            ).order_by('-created_on')[:20]

        # Prepare the data for rendering or serialization
        contracts_data = []
        for contract in last_20_contracts:
            # Get the first CLIN with clin_type_id=1 for this contract
            main_clin = contract.clin_set.filter(clin_type_id=1).first()
            if main_clin and main_clin.clin_finance and main_clin.supplier:
                contracts_data.append({
                    'id': contract.id,
                    'contract_number': contract.contract_number,
                    'supplier_name': main_clin.supplier.name,
                    'contract_value': main_clin.clin_finance.contract_value,
                    'award_date': contract.award_date,
                    'due_date': contract.due_date,
                })

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
                'new_contract_value': clins.aggregate(total=Sum('clin_finance__contract_value'))['total'] or 0,
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

        context['contracts'] = self.get_contracts()
        context['periods'] = periods
        return context


@method_decorator(conditional_login_required, name='dispatch')
class ContractDetailView(DetailView):
    model = Contract
    template_name = 'contracts/contract_detail.html'
    context_object_name = 'contract'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contract = self.get_object()
        clins = contract.clin_set.all().select_related(
            'clin_type', 'supplier', 'nsn'
        )
        context['clins'] = clins
        context['contract_notes'] = contract.contractnote_set.all().order_by('-created_on')
        
        # Get the default selected CLIN (type=1) or first CLIN if no type 1 exists
        context['selected_clin'] = clins.filter(clin_type_id=1).first() or clins.first()
        if context['selected_clin']:
            context['clin_notes'] = context['selected_clin'].clinnote_set.all().order_by('-created_on')
            try:
                context['acknowledgment'] = context['selected_clin'].clinacknowledgment_set.first()
            except:
                context['acknowledgment'] = None
        else:
            context['clin_notes'] = []
            context['acknowledgment'] = None
            
        return context


@method_decorator(conditional_login_required, name='dispatch')
class ClinDetailView(DetailView):
    model = Clin
    template_name = 'contracts/clin_detail.html'
    context_object_name = 'clin'

    def get_queryset(self):
        return super().get_queryset().select_related(
            'contract',
            'clin_type',
            'supplier',
            'nsn',
            'clin_finance',
            'clin_finance__special_payment_terms'
        )


@conditional_login_required
def contract_search(request):
    query = request.GET.get('q', '')
    if len(query) < 3:
        return JsonResponse([], safe=False)

    # Search by full contract number or last 6 characters
    contracts = Contract.objects.filter(
        Q(contract_number__icontains=query) |
        Q(contract_number__iendswith=query[-6:]) if len(query) >= 6 else Q()
    ).values(
        'id', 
        'contract_number'
    ).order_by('contract_number')[:10]

    return JsonResponse(list(contracts), safe=False)


@method_decorator(conditional_login_required, name='dispatch')
class NsnUpdateView(UpdateView):
    model = Nsn
    template_name = 'contracts/nsn_edit.html'
    context_object_name = 'nsn'
    form_class = NsnForm
    
    def get_success_url(self):
        next_url = self.request.GET.get('next')
        if next_url:
            return next_url
        return reverse_lazy('contracts:contracts_dashboard')


@method_decorator(conditional_login_required, name='dispatch')
class SupplierUpdateView(UpdateView):
    model = Supplier
    template_name = 'contracts/supplier_edit.html'
    context_object_name = 'supplier'
    form_class = SupplierForm
    
    def get_success_url(self):
        next_url = self.request.GET.get('next')
        if next_url:
            return next_url
        return reverse_lazy('contracts:contracts_dashboard')


@conditional_login_required
def get_clin_notes(request, clin_id):
    clin = get_object_or_404(Clin, id=clin_id)
    notes = clin.clinnote_set.all().order_by('-created_on')
    notes_data = [{
        'note': note.note,
        'created_by': str(note.created_by),
        'created_on': note.created_on.strftime("%b %d, %Y %H:%M")
    } for note in notes]
    return JsonResponse({'notes': notes_data})


@conditional_login_required
@require_http_methods(["POST"])
def toggle_clin_acknowledgment(request, clin_id):
    try:
        clin = Clin.objects.get(id=clin_id)
        data = json.loads(request.body)
        field = data.get('field')
        
        # Get or create acknowledgment
        acknowledgment, created = ClinAcknowledgment.objects.get_or_create(clin=clin)
        
        # Toggle the field
        current_value = getattr(acknowledgment, field)
        new_value = not current_value
        
        # Update the boolean field
        setattr(acknowledgment, field, new_value)
        
        # Update the corresponding date and user fields
        field_base = field.replace('_bool', '')
        date_field = f"{field_base}_date"
        user_field = f"{field_base}_user"
        
        if new_value:
            setattr(acknowledgment, date_field, timezone.now())
            setattr(acknowledgment, user_field, request.user.username)
        else:
            setattr(acknowledgment, date_field, None)
            setattr(acknowledgment, user_field, None)
        
        acknowledgment.save()
        
        return JsonResponse({
            'status': new_value,
            'date': getattr(acknowledgment, date_field).isoformat() if new_value else None
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
