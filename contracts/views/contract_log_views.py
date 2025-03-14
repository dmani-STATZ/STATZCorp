from django.shortcuts import render
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

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, Clin


class ContractLogView(ListView):
    model = Clin
    template_name = 'contracts/contract_log_view.html'
    context_object_name = 'clins'
    paginate_by = 15  # Enable pagination with 10 records per page
    
    def get_queryset(self):
        # Start with all CLINs and handle null relationships
        queryset = Clin.objects.all()
        
        # Add select_related for performance but don't filter out records with missing relationships
        queryset = queryset.select_related(
            'contract',
            'contract__buyer',
            'contract__contract_type',
            'contract__sales_class',
            'supplier',
            'nsn',
            'special_payment_terms'
        ).order_by('-contract__award_date', 'contract__po_number', 'id')
        
        # Check for repeat NSNs - include nulls
        repeat_nsn = Exists(
            Clin.objects.filter(
                nsn=OuterRef('nsn')
            ).exclude(
                id=OuterRef('id')
            ).filter(nsn__isnull=False)  # Only check repeats if NSN exists
        )
        
        # Apply filters if provided
        search_query = self.request.GET.get('search', '')
        status_filter = self.request.GET.get('status', '')
        class_filter = self.request.GET.get('class', '')
        
        if search_query:
            queryset = queryset.filter(
                Q(contract__contract_number__icontains=search_query) |
                Q(contract__po_number__icontains=search_query) |
                Q(contract__tab_num__icontains=search_query) |
                Q(contract__buyer__username__icontains=search_query) |
                Q(nsn__nsn__icontains=search_query) |
                Q(po_num_ext__icontains=search_query)  # Added PO Num Ext to search
            ).distinct()
        
        if status_filter:
            if status_filter == 'open':
                queryset = queryset.filter(
                    Q(contract__cancelled=False) & 
                    Q(contract__date_closed__isnull=True)
                )
            elif status_filter == 'closed':
                queryset = queryset.filter(
                    Q(contract__cancelled=False) & 
                    Q(contract__date_closed__isnull=False)
                )
            elif status_filter == 'cancelled':
                queryset = queryset.filter(contract__cancelled=True)
        
        if class_filter:
            queryset = queryset.filter(contract__sales_class=class_filter)
        
        # Annotate additional fields for color coding and display
        queryset = queryset.annotate(
            is_idiq=Case(
                When(contract__idiq_contract__isnull=False, then=True),
                default=False,
                output_field=BooleanField()
            ),
            is_repeat=repeat_nsn,
            is_late=Case(
                When(contract__due_date_late=True, then=True),
                default=False,
                output_field=BooleanField()
            ),
            is_late_shipment=Case(
                When(ship_date_late=True, then=True),
                default=False,
                output_field=BooleanField()
            ),
            is_paid=Case(
                When(
                    Q(paid_amount__isnull=False) & 
                    Q(clin_value__isnull=False) & 
                    Q(paid_amount__gte=F('clin_value')), 
                    then=True
                ),
                default=False,
                output_field=BooleanField()
            ),
            payment_type=Case(
                When(special_payment_terms__code='CIA', then=Value('CIA')),
                When(special_payment_terms__code='COS', then=Value('COS')),
                default=Value('NET'),
                output_field=CharField()
            )
        )
        
        # Ensure we have a valid queryset
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add filter parameters to context
        context['search_query'] = self.request.GET.get('search', '')
        context['status_filter'] = self.request.GET.get('status', '')
        context['class_filter'] = self.request.GET.get('class', '')
        
        # Add contract classes for the filter dropdown
        context['classes'] = Contract.objects.values_list('sales_class__sales_team', flat=True).distinct()
        
        # Debug information
        context['total_records'] = Clin.objects.count()
        
        # Ensure paginator data is explicitly available in the template
        if self.paginate_by is not None:
            paginator = context.get('paginator')
            page_obj = context.get('page_obj')
            if paginator and page_obj:
                context['is_paginated'] = True
                context['page_obj'] = page_obj
                context['paginator'] = paginator
                context['page_range'] = paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
        
        return context


@conditional_login_required
def export_contract_log(request):
    """Export contract log to CSV with all relevant fields."""
    # Get all CLINs with related data
    clins = Clin.objects.all()
    
    # Add select_related for performance but don't filter out records with missing relationships
    clins = clins.select_related(
        'contract',
        'contract__buyer',
        'contract__contract_type',
        'contract__sales_class',
        'supplier',
        'nsn',
        'special_payment_terms'
    ).order_by('-contract__award_date', 'contract__po_number', 'id')
    
    # Apply filters if provided
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    class_filter = request.GET.get('class', '')
    
    if search_query:
        clins = clins.filter(
            Q(contract__contract_number__icontains=search_query) |
            Q(contract__po_number__icontains=search_query) |
            Q(contract__tab_num__icontains=search_query) |
            Q(contract__buyer__username__icontains=search_query) |
            Q(nsn__nsn__icontains=search_query) |
            Q(po_num_ext__icontains=search_query)
        ).distinct()
    
    if status_filter:
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
    
    if class_filter:
        clins = clins.filter(contract__sales_class=class_filter)
    
    # Create response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="contract_log.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Status', 'Tab Num', 'PO Number', 'PO Num Ext', 'Contract Num', 'Buyer', 'Contract Type',
        'Supplier', 'Award Date', 'Contract Status', 'NSN', 'NSN Description', 'IA',
        'PO Sent to Supplier', 'CLIN has Replied', 'PO Sent to QAR', 'FOB',
        'CLIN Due Date', 'Contract Due Date', 'Order QTY', 'Ship Date', 'Ship QTY',
        'CLIN Value', 'Paid Amount', 'Contract Value', 'WAWF Payment', 'WAWF Received',
        'Plan Gross', 'PPI Split Paid', 'STATZ Split Paid', 'Payment Type',
        'Is IDIQ', 'Is Repeat', 'Is Late', 'Notes'
    ])
    
    for clin in clins:
        # Handle potentially missing relationships safely
        contract = clin.contract if hasattr(clin, 'contract') else None
        buyer = contract.buyer if contract and hasattr(contract, 'buyer') else None
        contract_type = contract.contract_type if contract and hasattr(contract, 'contract_type') else None
        supplier = clin.supplier if hasattr(clin, 'supplier') else None
        nsn = clin.nsn if hasattr(clin, 'nsn') else None
        special_payment_terms = clin.special_payment_terms if hasattr(clin, 'special_payment_terms') else None
        
        # Check for repeat NSN only if NSN exists
        is_repeat = 'Yes' if nsn and Clin.objects.filter(nsn=nsn).exclude(id=clin.id).exists() else 'No'
        
        writer.writerow([
            'Cancelled' if contract and contract.cancelled else 'Closed' if contract and contract.date_closed else 'Open',
            contract.tab_num if contract else '',
            contract.po_number if contract else '',
            clin.po_num_ext or '',
            contract.contract_number if contract else '',
            buyer.username if buyer else '',
            contract_type.code if contract_type else '',
            supplier.code if supplier else '',
            contract.award_date.strftime('%Y-%m-%d') if contract and contract.award_date else '',
            'Active' if contract and not contract.cancelled and not contract.date_closed else 'Closed' if contract and contract.date_closed else 'Cancelled' if contract and contract.cancelled else '',
            nsn.nsn if nsn else '',
            nsn.description if nsn else '',
            'Yes' if clin.ia else 'No',
            'Yes' if clin.clinacknowledgment_set.filter(sent_to_supplier=True).exists() else 'No',
            'Yes' if clin.clinacknowledgment_set.filter(supplier_replied=True).exists() else 'No',
            'Yes' if clin.clinacknowledgment_set.filter(sent_to_qar=True).exists() else 'No',
            clin.fob or '',
            clin.due_date.strftime('%Y-%m-%d') if clin.due_date else '',
            contract.due_date.strftime('%Y-%m-%d') if contract and contract.due_date else '',
            clin.order_qty or '',
            clin.ship_date.strftime('%Y-%m-%d') if clin.ship_date else '',
            clin.ship_qty or '',
            f"${clin.clin_value:,.2f}" if clin.clin_value else '',
            f"${clin.paid_amount:,.2f}" if clin.paid_amount else '',
            f"${contract.contract_value:,.2f}" if contract and contract.contract_value else '',
            f"${clin.wawf_payment:,.2f}" if clin.wawf_payment else '',
            'Yes' if clin.wawf_recieved else 'No',
            f"${clin.plan_gross:,.2f}" if clin.plan_gross else '',
            f"${clin.ppi_split_paid:,.2f}" if clin.ppi_split_paid else '',
            f"${clin.statz_split_paid:,.2f}" if clin.statz_split_paid else '',
            special_payment_terms.code if special_payment_terms else 'NET',
            'Yes' if contract and contract.idiq_contract else 'No',
            is_repeat,
            'Yes' if contract and contract.due_date_late else 'No',
            contract.notes if contract else ''
        ])
    
    return response


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