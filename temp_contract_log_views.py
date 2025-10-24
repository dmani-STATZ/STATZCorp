from django.shortcuts import render, redirect
from django.views.generic import ListView
from django.utils.decorators import method_decorator
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, F, Value, CharField, Case, When, BooleanField, Exists, OuterRef, Subquery, Max, Count
from django.db.models.functions import Concat
from django.utils import timezone
import csv
import os
import subprocess
from django.conf import settings
import sys
from decimal import Decimal
import time

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, Clin, ClinAcknowledgment, Supplier, ExportTiming


class ContractLogView(ListView):
    model = Clin
    template_name = 'contracts/contract_log_view.html'
    context_object_name = 'clins'
    paginate_by = 25
    
    def get_queryset(self):
        """Get the list of CLINs for this view."""
        clins = Clin.objects.filter(company=self.request.active_company).select_related(
            'contract',
            'contract__buyer',
            'contract__contract_type',
            'contract__status',
            'contract__idiq_contract',
            'supplier',
            'nsn'
        ).prefetch_related(
            'clinacknowledgment_set'
        ).order_by('contract__award_date', 'contract__po_number', 'item_number')
        
        # Apply filters if provided
        search_query = self.request.GET.get('search', '')
        status_filter = self.request.GET.get('status', '')
        supplier_filter = self.request.GET.get('supplier', '')
        
        if search_query:
            clins = clins.filter(
                Q(contract__contract_number__icontains=search_query) |
                Q(contract__po_number__icontains=search_query) |
                Q(contract__tab_num__icontains=search_query) |
                Q(supplier__name__icontains=search_query) |
                Q(nsn__nsn_code__icontains=search_query) |
                Q(item_number__icontains=search_query)
            ).distinct()
        
        if status_filter:
            if status_filter == 'open':
                clins = clins.filter(
                    Q(contract__status__description='Open') &
                    Q(contract__date_closed__isnull=True)
                )
            elif status_filter == 'closed':
                clins = clins.filter(
                    Q(contract__status__description='Closed') &
                    Q(contract__date_closed__isnull=False)
                )
            elif status_filter == 'cancelled':
                clins = clins.filter(contract__status__description='Cancelled')
        
        if supplier_filter:
            # Get all contract IDs that have any CLIN with the specified supplier
            contract_ids = Clin.objects.filter(
                supplier_id=supplier_filter
            , company=self.request.active_company).values_list('contract_id', flat=True).distinct()
            
            # Filter CLINs to show all CLINs from the matched contracts
            clins = clins.filter(contract_id__in=contract_ids)
        
        return clins
    
    def get(self, request, *args, **kwargs):
        # If no page is specified, calculate and redirect to the last page
        if 'page' not in request.GET:
            queryset = self.get_queryset()
            paginator = self.get_paginator(queryset, self.paginate_by)
            # Get the URL parameters excluding the page parameter
            params = request.GET.copy()
            # Add the last page number
            params['page'] = paginator.num_pages
            # Redirect to the last page with all other parameters preserved
            return redirect(f"{request.path}?{params.urlencode()}")
        return super().get(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add filter parameters to context
        context['search_query'] = self.request.GET.get('search', '')
        context['status_filter'] = self.request.GET.get('status', '')
        context['supplier_filter'] = self.request.GET.get('supplier', '')
        
        # Add suppliers list for the dropdown
        context['suppliers'] = Supplier.objects.all().order_by('name')
        
        # Ensure paginator data is explicitly available in the template
        if self.paginate_by is not None:
            paginator = context.get('paginator')
            page_obj = context.get('page_obj')
            if paginator and page_obj:
                context['is_paginated'] = True
                context['page_obj'] = page_obj
                context['paginator'] = paginator
        
        return context


@conditional_login_required
def export_contract_log(request):
    """Export contract log to CSV with all relevant fields."""
    start_time = time.time()
    
    # Get all CLINs with related data
    clins = Clin.objects.filter(company=request.active_company).select_related(
        'contract',
        'contract__buyer',
        'contract__contract_type',
        'contract__status',
        'contract__idiq_contract',
        'supplier',
        'nsn'
    ).prefetch_related(
        'clinacknowledgment_set'  # Use prefetch_related for reverse relation
    ).order_by('contract__award_date', 'contract__po_number', 'item_number')
    
    # Apply filters if provided
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    supplier_filter = request.GET.get('supplier', '')
    
    filters_applied = {}
    
    if search_query:
        filters_applied['search'] = search_query
        clins = clins.filter(
            Q(contract__contract_number__icontains=search_query) |
            Q(contract__po_number__icontains=search_query) |
            Q(contract__tab_num__icontains=search_query) |
            Q(supplier__name__icontains=search_query) |
            Q(nsn__nsn_code__icontains=search_query) |
            Q(item_number__icontains=search_query)
        ).distinct()
    
    if status_filter:
        filters_applied['status'] = status_filter
        if status_filter == 'open':
            clins = clins.filter(
                Q(contract__cancelled=False) & 
                Q(contract__date_closed__isnull=True)
            )
        elif status_filter == 'closed':
            clins = clins.filter(
                Q(contract__cancelled=False) & 
                Q(contract__date_closed__isnull=False)
            )
        elif status_filter == 'cancelled':
            clins = clins.filter(contract__cancelled=True)
    
    if supplier_filter:
        filters_applied['supplier'] = supplier_filter
        # Get all contract IDs that have any CLIN with the specified supplier
        contract_ids = Clin.objects.filter(
            supplier_id=supplier_filter
        ).values_list('contract_id', flat=True).distinct()
        
        # Filter CLINs to show all CLINs from the matched contracts
        clins = clins.filter(contract_id__in=contract_ids)
    
    # Create response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="contract_log.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Status', 'Tab #', 'PO #', 'IDIQ Contract #', 'Contract #', 'Buyer', 'Type', 'CLIN #',
        'Supplier', 'Award Date', 'Contract Status', 'NSN', 'NSN Description',
        'IA', 'PO to Sub', 'Sub Reply', 'PO to QAR', 'FOB', 'QDD', 'CDD',
        'Order Qty', 'Ship Date', 'Ship Qty', 'Sub PO $', 'Sub Paid $', 'X',
        'Contract $', 'WAWF Payment $', 'Date Pay Recv', 'Plan Gross $',
        'Actual Paid PPI $', 'Actual STATZ $', 'Plan Split per PPI bid',
        'PPI Split $', 'STATZ Split $', 'Notes'
    ])
    
    # Get total count before writing rows
    total_rows = clins.count()
    
    for clin in clins:
        # Get the first acknowledgment for the CLIN (if any)
        acknowledgment = clin.clinacknowledgment_set.first()
        
        writer.writerow([
            'Cancelled' if clin.contract.status.description == 'Cancelled' else 'Closed' if clin.contract.date_closed else 'Open',
            clin.contract.tab_num,
            clin.contract.po_number,
            clin.contract.idiq_contract.contract_number if clin.contract.idiq_contract else '',
            clin.contract.contract_number,
            clin.contract.buyer.description if clin.contract.buyer else '',
            clin.contract.contract_type.description if clin.contract.contract_type else '',
            clin.item_number,
            clin.supplier.name if clin.supplier else '',
            clin.contract.award_date.strftime('%m/%d/%Y') if clin.contract.award_date else '',
            clin.contract.status.description if clin.contract.status else '',
            clin.nsn.nsn_code if clin.nsn else '',
            clin.nsn.description if clin.nsn else '',
            clin.ia,
            'Yes' if acknowledgment and acknowledgment.po_to_supplier_bool else 'No',
            'Yes' if acknowledgment and acknowledgment.clin_reply_bool else 'No',
            'Yes' if acknowledgment and acknowledgment.po_to_qar_bool else 'No',
            clin.fob,
            clin.supplier_due_date.strftime('%m/%d/%Y') if clin.supplier_due_date else '',
            clin.due_date.strftime('%m/%d/%Y') if clin.due_date else '',
            f"{clin.order_qty} {clin.uom}" if clin.order_qty else '',
            clin.ship_date.strftime('%m/%d/%Y') if clin.ship_date else '',
            clin.ship_qty,
            f"${clin.quote_value:,.2f}" if clin.quote_value else '',
            f"${clin.paid_amount:,.2f}" if clin.paid_amount else '',
            '',  # X column
            f"${clin.contract.contract_value:,.2f}" if clin.contract.contract_value else '',
            f"${clin.wawf_payment:,.2f}" if clin.wawf_payment else '',
            clin.wawf_recieved.strftime('%m/%d/%Y') if clin.wawf_recieved else '',
            # f"${clin.plan_gross:,.2f}" if clin.plan_gross else '',  # Moved to contract
            #f"${clin.contract.ppi_split_paid:,.2f}" if clin.contract.ppi_split_paid else '',  # Moved to splits table
            #f"${clin.contract.statz_split_paid:,.2f}" if clin.contract.statz_split_paid else '',  # Moved to splits table
            # clin.contract.planned_split,  # Need to move planned split to contract
            #f"${clin.contract.ppi_split:,.2f}" if clin.contract.ppi_split else '',  # Moved to splits table
            #f"${clin.contract.statz_split:,.2f}" if clin.contract.statz_split else '',  # Moved to splits table
            clin.notes.count()
        ])
    
    # Record the export timing
    end_time = time.time()
    export_time = end_time - start_time
    
    ExportTiming.objects.create(
        row_count=total_rows,
        export_time=export_time,
        filters_applied=filters_applied
    )
    
    return response


@conditional_login_required
def get_export_estimate(request):
    """Get estimated export time based on row count."""
    row_count = int(request.GET.get('rows', 0))
    estimated_time = ExportTiming.get_estimated_time(row_count)
    return JsonResponse({
        'estimated_seconds': estimated_time,
        'recent_timings': list(ExportTiming.objects.values('row_count', 'export_time', 'timestamp')[:5])
    })


@conditional_login_required
def open_export_folder(request):
    """Open the export folder in the file explorer."""
    export_folder = os.path.join(settings.MEDIA_ROOT, 'exports')
    os.makedirs(export_folder, exist_ok=True)
    
    if sys.platform == 'win32':
        os.startfile(export_folder)
    elif sys.platform == 'darwin':  # macOS
        subprocess.run(['open', export_folder])
    else:  # Linux
        subprocess.run(['xdg-open', export_folder])
    
    return JsonResponse({'success': True}) 
