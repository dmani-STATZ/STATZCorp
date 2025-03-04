from django.shortcuts import render
from django.views.generic import ListView
from django.utils.decorators import method_decorator
from django.http import HttpResponse
from django.db.models import Q, F, Value, CharField
from django.db.models.functions import Concat
import csv
import os
import subprocess
from django.conf import settings
import sys
from decimal import Decimal

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, Clin


class ContractLogView(ListView):
    model = Contract
    template_name = 'contracts/contract_log_view.html'
    context_object_name = 'contracts'
    paginate_by = 50
    
    def get_queryset(self):
        queryset = Contract.objects.all().order_by('-created_at')
        
        # Apply filters if provided
        search_query = self.request.GET.get('search', '')
        status_filter = self.request.GET.get('status', '')
        
        if search_query:
            queryset = queryset.filter(
                Q(contract_num__icontains=search_query) |
                Q(title__icontains=search_query) |
                Q(supplier__name__icontains=search_query)
            )
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add filter parameters to context
        context['search_query'] = self.request.GET.get('search', '')
        context['status_filter'] = self.request.GET.get('status', '')
        
        # Add status options for the filter dropdown
        context['status_options'] = [
            'Active',
            'Closed',
            'Cancelled'
        ]
        
        return context


@conditional_login_required
def export_contract_log(request):
    # Get all contracts
    contracts = Contract.objects.all().order_by('-created_at')
    
    # Apply filters if provided
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    
    if search_query:
        contracts = contracts.filter(
            Q(contract_num__icontains=search_query) |
            Q(title__icontains=search_query) |
            Q(supplier__name__icontains=search_query)
        )
    
    if status_filter:
        contracts = contracts.filter(status=status_filter)
    
    # Create a response with CSV content
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="contract_log.csv"'
    
    # Create CSV writer
    writer = csv.writer(response)
    
    # Write header row
    writer.writerow([
        'Contract Number',
        'Title',
        'Supplier',
        'Status',
        'Created Date',
        'Created By',
        'Closed Date',
        'Closed By',
        'Cancelled Date',
        'Cancelled By',
        'Total CLINs',
        'Acknowledged CLINs',
        'Rejected CLINs',
        'Pending CLINs',
        'Total Obligated',
        'Total Invoiced'
    ])
    
    # Write data rows
    for contract in contracts:
        # Get CLIN counts and financial totals
        clins = contract.clin_set.all()
        total_clins = clins.count()
        acknowledged_clins = clins.filter(clinacknowledgment__acknowledged=True).count()
        rejected_clins = clins.filter(clinacknowledgment__rejected=True).count()
        pending_clins = total_clins - acknowledged_clins - rejected_clins
        
        from django.db.models import Sum
        total_obligated = clins.aggregate(Sum('clinfinance__obligated_amt'))['clinfinance__obligated_amt__sum'] or Decimal('0.00')
        total_invoiced = clins.aggregate(Sum('clinfinance__invoiced_amt'))['clinfinance__invoiced_amt__sum'] or Decimal('0.00')
        
        writer.writerow([
            contract.contract_num,
            contract.title,
            contract.supplier.name if contract.supplier else '',
            contract.status,
            contract.created_at.strftime('%Y-%m-%d') if contract.created_at else '',
            contract.created_by.username if contract.created_by else '',
            contract.closed_date.strftime('%Y-%m-%d') if contract.closed_date else '',
            contract.closed_by.username if contract.closed_by else '',
            contract.cancelled_date.strftime('%Y-%m-%d') if contract.cancelled_date else '',
            contract.cancelled_by.username if contract.cancelled_by else '',
            total_clins,
            acknowledged_clins,
            rejected_clins,
            pending_clins,
            f"${total_obligated:,.2f}",
            f"${total_invoiced:,.2f}"
        ])
    
    return response


@conditional_login_required
def open_export_folder(request):
    """
    Open the export folder in the file explorer.
    """
    export_folder = os.path.join(settings.MEDIA_ROOT, 'exports')
    
    # Create the folder if it doesn't exist
    os.makedirs(export_folder, exist_ok=True)
    
    # Open the folder based on the operating system
    if sys.platform == 'win32':
        os.startfile(export_folder)
    elif sys.platform == 'darwin':  # macOS
        subprocess.run(['open', export_folder])
    else:  # Linux
        subprocess.run(['xdg-open', export_folder])
    
    return HttpResponse('Export folder opened.') 