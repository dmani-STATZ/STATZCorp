from django.shortcuts import render, redirect
from django.views.generic import ListView
from django.utils.decorators import method_decorator
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, F, Value, CharField, Case, When, BooleanField, Exists, OuterRef, Subquery, Max, Count, Sum
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
            'clinacknowledgment_set',
            'contract__splits',
        ).annotate(
            # Aggregated split values for PPI and STATZ at the contract level
            ppi_split_value=Sum('contract__splits__split_value', filter=Q(contract__splits__company_name__iexact='PPI')),
            ppi_split_paid=Sum('contract__splits__split_paid', filter=Q(contract__splits__company_name__iexact='PPI')),
            statz_split_value=Sum('contract__splits__split_value', filter=Q(contract__splits__company_name__iexact='STATZ')),
            statz_split_paid=Sum('contract__splits__split_paid', filter=Q(contract__splits__company_name__iexact='STATZ')),
            # Flag first CLIN per contract via subquery (SQLite-safe)
            is_first_for_contract=Case(
                When(
                    id=Subquery(
                        Clin.objects
                        .filter(contract_id=OuterRef('contract_id'))
                        .order_by('item_number', 'id')
                        .values('id')[:1]
                    ),
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField(),
            ),
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
        
        # Build derived status text for each CLIN (used by UI Contract Status column)
        page_obj = context.get('page_obj')
        if page_obj:
            def build_status_text(clin):
                parts = []
                if getattr(clin.contract, 'status', None) and getattr(clin.contract.status, 'description', ''):
                    parts.append(clin.contract.status.description)
                # Use first acknowledgment if present
                ack = None
                try:
                    ack = clin.clinacknowledgment_set.first()
                except Exception:
                    ack = None
                # Per business rule: add notes when flags are false/missing
                if not (ack and ack.po_to_supplier_bool):
                    parts.append('PO NOT SENT YET;')
                if not (ack and ack.clin_reply_bool):
                    parts.append('SUB REPLY NEEDED;')
                if not (ack and ack.po_to_qar_bool):
                    parts.append('PO TO QAR NEEDED;')
                return ' '.join(parts).strip()

            for clin in page_obj.object_list:
                try:
                    clin.contract_status_text = build_status_text(clin)
                except Exception:
                    clin.contract_status_text = getattr(clin.contract.status, 'description', '') if getattr(clin, 'contract', None) and getattr(clin.contract, 'status', None) else ''

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
        'clinacknowledgment_set',  # Use prefetch_related for reverse relation
        'contract__splits',        # Prefetch splits for computing PPI/STATZ amounts
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
        filters_applied['supplier'] = supplier_filter
        # Get all contract IDs that have any CLIN with the specified supplier
        contract_ids = Clin.objects.filter(
            supplier_id=supplier_filter,
            company=request.active_company,
        ).values_list('contract_id', flat=True).distinct()
        
        # Filter CLINs to show all CLINs from the matched contracts
        clins = clins.filter(contract_id__in=contract_ids)
    
    # Create response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="contract_log.csv"'
    
    writer = csv.writer(response)
    # Column order aligned to the Master Log, with additions:
    # Keep IDIQ Contract #, add CLIN #, use PO # label, and add Cage Code.
    writer.writerow([
        'Open', 'Tab #', 'PO #', 'IDIQ Contract #', 'Contract', 'Buyer', 'Type', 'CLIN #',
        'Supplier', 'Cage Code', 'Award Date', 'Contract Status', 'NSN', 'Item Description',
        'I&A', 'PO to Sub', 'Sub Reply', 'PO to QAR', 'FOB', 'QDD', 'CDD', 'Order Qty',
        'Ship Date', 'Ship Qty', 'Sub PO $', 'Sub Paid $', 'Terms', 'Contract $',
        'WAWF Payment $', 'Date Pay Recv', 'Plan Gross $', 'Actual Paid PPI $', 'Actual STATZ $',
        'Plan Split per PPI bid', 'PPI Split $', 'STATZ Split $', 'Notes'
    ])
    
    # Get total count before writing rows
    total_rows = clins.count()
    
    seen_contracts = set()
    for clin in clins:
        # Get the first acknowledgment for the CLIN (if any)
        acknowledgment = clin.clinacknowledgment_set.first()
        first_for_contract = False
        if clin.contract_id not in seen_contracts:
            first_for_contract = True
            seen_contracts.add(clin.contract_id)
        
        # Compute split-related amounts once per row from prefetched splits
        splits = list(clin.contract.splits.all()) if clin.contract_id else []
        def _sum_for(name, attr):
            target = (name or '').strip().upper()
            total = Decimal('0')
            for s in splits:
                if ((s.company_name or '').strip().upper() == target) and getattr(s, attr) is not None:
                    total += Decimal(str(getattr(s, attr)))
            return total

        ppi_split_paid = _sum_for('PPI', 'split_paid')
        statz_split_paid = _sum_for('STATZ', 'split_paid')
        ppi_split_value = _sum_for('PPI', 'split_value')
        statz_split_value = _sum_for('STATZ', 'split_value')

        # Map first column to single-letter status like Master Log (O/C/X)
        if clin.contract and clin.contract.status and getattr(clin.contract.status, 'description', '') == 'Cancelled':
            first_col_status = 'X'
        elif clin.contract and clin.contract.date_closed:
            first_col_status = 'C'
        else:
            first_col_status = 'O'

        # PO # shown (previously Sub PO # in legacy export)
        po_num = clin.po_number or clin.clin_po_num or (clin.contract.po_number if clin.contract else '')

        # Special payment terms text: use Contract.special_payment_terms only (no fallback)
        terms_text = ''
        c_terms = getattr(clin.contract, 'special_payment_terms', None) if getattr(clin, 'contract', None) else None
        if c_terms is not None:
            terms_text = getattr(c_terms, 'terms', None) or getattr(c_terms, 'code', '') or ''

        # Derived contract status text for export
        status_parts = []
        if clin.contract and getattr(clin.contract, 'status', None) and getattr(clin.contract.status, 'description', ''):
            status_parts.append(clin.contract.status.description)
        if not (acknowledgment and acknowledgment.po_to_supplier_bool):
            status_parts.append('PO NOT SENT YET;')
        if not (acknowledgment and acknowledgment.clin_reply_bool):
            status_parts.append('SUB REPLY NEEDED;')
        if not (acknowledgment and acknowledgment.po_to_qar_bool):
            status_parts.append('PO TO QAR NEEDED;')
        contract_status_text = ' '.join(status_parts).strip()

        writer.writerow([
            first_col_status,
            clin.contract.tab_num if clin.contract else '',
            po_num,
            (clin.contract.idiq_contract.contract_number if clin.contract and clin.contract.idiq_contract else ''),
            clin.contract.contract_number if clin.contract else '',
            clin.contract.buyer.description if clin.contract and clin.contract.buyer else '',
            clin.contract.contract_type.description if clin.contract and clin.contract.contract_type else '',
            clin.item_number or '',
            clin.supplier.name if clin.supplier else '',
            clin.supplier.cage_code if clin.supplier else '',
            clin.contract.award_date.strftime('%m/%d/%Y') if clin.contract and clin.contract.award_date else '',
            contract_status_text,
            clin.nsn.nsn_code if clin.nsn else '',
            clin.nsn.description if clin.nsn else '',
            clin.ia or '',
            '1' if acknowledgment and acknowledgment.po_to_supplier_bool else '0',
            '1' if acknowledgment and acknowledgment.clin_reply_bool else '0',
            '1' if acknowledgment and acknowledgment.po_to_qar_bool else '0',
            clin.fob or '',
            clin.supplier_due_date.strftime('%m/%d/%Y') if clin.supplier_due_date else '',
            clin.due_date.strftime('%m/%d/%Y') if clin.due_date else '',
            f"{clin.order_qty:g}" if clin.order_qty not in (None, '') else '',
            clin.ship_date.strftime('%m/%d/%Y') if clin.ship_date else '',
            f"{clin.ship_qty:g}" if clin.ship_qty not in (None, '') else '',
            f"${clin.quote_value:,.2f}" if clin.quote_value else '',
            f"${clin.paid_amount:,.2f}" if clin.paid_amount else '',
            terms_text,
            f"${clin.contract.contract_value:,.2f}" if clin.contract and clin.contract.contract_value else '',
            f"${clin.wawf_payment:,.2f}" if clin.wawf_payment else '',
            clin.wawf_recieved.strftime('%m/%d/%Y') if clin.wawf_recieved else '',
            f"${clin.contract.plan_gross:,.2f}" if (first_for_contract and clin.contract and clin.contract.plan_gross is not None) else '$0.00',
            f"${ppi_split_paid:,.2f}" if (first_for_contract and ppi_split_paid) else '$0.00',
            f"${statz_split_paid:,.2f}" if (first_for_contract and statz_split_paid) else '$0.00',
            (clin.contract.planned_split or '') if (first_for_contract and clin.contract) else '',
            f"${ppi_split_value:,.2f}" if (first_for_contract and ppi_split_value) else '$0.00',
            f"${statz_split_value:,.2f}" if (first_for_contract and statz_split_value) else '$0.00',
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
def export_contract_log_xlsx(request):
    """Export contract log to XLSX with workbook-like structure."""
    start_time = time.time()
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, NamedStyle
    except Exception as e:
        # Graceful message if dependency missing
        return HttpResponse(
            f"Missing dependency for XLSX export: {e}. Please install 'openpyxl'.",
            status=500,
            content_type='text/plain'
        )

    # Query same data as CSV export
    clins = Clin.objects.filter(company=request.active_company).select_related(
        'contract',
        'contract__buyer',
        'contract__contract_type',
        'contract__status',
        'contract__idiq_contract',
        'contract__special_payment_terms',
        'supplier',
        'nsn'
    ).prefetch_related(
        'clinacknowledgment_set',
        'contract__splits',
    ).order_by('contract__award_date', 'contract__po_number', 'item_number')

    # Filters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    supplier_filter = request.GET.get('supplier', '')

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
        contract_ids = Clin.objects.filter(
            supplier_id=supplier_filter,
            company=request.active_company,
        ).values_list('contract_id', flat=True).distinct()
        clins = clins.filter(contract_id__in=contract_ids)

    # Prepare workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'MASTER CONTRACT LOG Export'

    # Styles
    bold = Font(bold=True)
    header_fill = PatternFill('solid', fgColor='F2F2F2')
    center = Alignment(horizontal='center', vertical='center')
    thin = Side(border_style='thin', color='DDDDDD')
    border = Border(top=thin, left=thin, right=thin, bottom=thin)

    # Title rows
    company_name = getattr(getattr(request, 'active_company', None), 'name', 'STATZ Corporation')
    ws.append([company_name])
    from datetime import datetime
    now = datetime.now()
    ws.append([f"Government Contracting Log - Master List", '', '', f"Export @ {now.strftime('%I:%M:%S %p')}"])
    ws.append([])

    # Header row
    headers = [
        'Open', 'Tab #', 'PO #', 'IDIQ Contract #', 'Contract', 'Buyer', 'Type', 'CLIN #',
        'Supplier', 'Cage Code', 'Award Date', 'Contract Status', 'NSN', 'Item Description',
        'I&A', 'PO to Sub', 'Sub Reply', 'PO to QAR', 'FOB', 'QDD', 'CDD', 'Order Qty',
        'Ship Date', 'Ship Qty', 'Sub PO $', 'Sub Paid $', 'Terms', 'Contract $',
        'WAWF Payment $', 'Date Pay Recv', 'Plan Gross $', 'Actual Paid PPI $', 'Actual STATZ $',
        'Plan Split per PPI bid', 'PPI Split $', 'STATZ Split $', 'Notes'
    ]
    ws.append(headers)
    for col in range(1, len(headers) + 1):
        c = ws.cell(row=4, column=col)
        c.font = bold
        c.fill = header_fill
        c.alignment = center
        c.border = border

    # Data rows
    seen_contracts = set()
    # 1-indexed columns matching currency fields in headers
    money_cols = {25, 26, 28, 31, 32, 33, 35, 36}
    for clin in clins:
        ack = clin.clinacknowledgment_set.first()
        first_for_contract = False
        if clin.contract_id not in seen_contracts:
            first_for_contract = True
            seen_contracts.add(clin.contract_id)

        # Splits
        splits = list(clin.contract.splits.all()) if clin.contract_id else []
        def _sum_for(name, attr):
            from decimal import Decimal as D
            target = (name or '').strip().upper()
            total = D('0')
            for s in splits:
                if ((s.company_name or '').strip().upper() == target) and getattr(s, attr) is not None:
                    total += D(str(getattr(s, attr)))
            return total
        ppi_split_paid = _sum_for('PPI', 'split_paid')
        statz_split_paid = _sum_for('STATZ', 'split_paid')
        ppi_split_value = _sum_for('PPI', 'split_value')
        statz_split_value = _sum_for('STATZ', 'split_value')

        # Derived status char
        if clin.contract and clin.contract.status and getattr(clin.contract.status, 'description', '') == 'Cancelled':
            status_char = 'X'
        elif clin.contract and clin.contract.date_closed:
            status_char = 'C'
        else:
            status_char = 'O'

        # Derived status text
        parts = []
        if clin.contract and getattr(clin.contract, 'status', None) and getattr(clin.contract.status, 'description', ''):
            parts.append(clin.contract.status.description)
        if not (ack and ack.po_to_supplier_bool):
            parts.append('PO NOT SENT YET;')
        if not (ack and ack.clin_reply_bool):
            parts.append('SUB REPLY NEEDED;')
        if not (ack and ack.po_to_qar_bool):
            parts.append('PO TO QAR NEEDED;')
        status_text = ' '.join(parts).strip()

        # Terms text: only contract-level
        terms = ''
        if clin.contract and getattr(clin.contract, 'special_payment_terms', None):
            spt = clin.contract.special_payment_terms
            terms = getattr(spt, 'terms', None) or getattr(spt, 'code', '') or ''

        row = [
            status_char,
            clin.contract.tab_num if clin.contract else '',
            (clin.po_number or clin.clin_po_num or (clin.contract.po_number if clin.contract else '')),
            (clin.contract.idiq_contract.contract_number if clin.contract and clin.contract.idiq_contract else ''),
            clin.contract.contract_number if clin.contract else '',
            clin.contract.buyer.description if clin.contract and clin.contract.buyer else '',
            clin.contract.contract_type.description if clin.contract and clin.contract.contract_type else '',
            clin.item_number or '',
            clin.supplier.name if clin.supplier else '',
            clin.supplier.cage_code if clin.supplier else '',
            clin.contract.award_date.strftime('%m/%d/%Y') if clin.contract and clin.contract.award_date else '',
            status_text,
            clin.nsn.nsn_code if clin.nsn else '',
            clin.nsn.description if clin.nsn else '',
            clin.ia or '',
            1 if (ack and ack.po_to_supplier_bool) else 0,
            1 if (ack and ack.clin_reply_bool) else 0,
            1 if (ack and ack.po_to_qar_bool) else 0,
            clin.fob or '',
            clin.supplier_due_date.strftime('%m/%d/%Y') if clin.supplier_due_date else '',
            clin.due_date.strftime('%m/%d/%Y') if clin.due_date else '',
            float(clin.order_qty) if clin.order_qty not in (None, '') else '',
            clin.ship_date.strftime('%m/%d/%Y') if clin.ship_date else '',
            float(clin.ship_qty) if clin.ship_qty not in (None, '') else '',
            float(clin.quote_value) if clin.quote_value else '',
            float(clin.paid_amount) if clin.paid_amount else '',
            terms,
            float(clin.contract.contract_value) if clin.contract and clin.contract.contract_value else '',
            float(clin.wawf_payment) if clin.wawf_payment else '',
            clin.wawf_recieved.strftime('%m/%d/%Y') if clin.wawf_recieved else '',
            float(clin.contract.plan_gross) if (first_for_contract and clin.contract and clin.contract.plan_gross is not None) else 0.0,
            float(ppi_split_paid) if (first_for_contract and ppi_split_paid) else 0.0,
            float(statz_split_paid) if (first_for_contract and statz_split_paid) else 0.0,
            (clin.contract.planned_split or '') if (first_for_contract and clin.contract) else '',
            float(ppi_split_value) if (first_for_contract and ppi_split_value) else 0.0,
            float(statz_split_value) if (first_for_contract and statz_split_value) else 0.0,
            int(clin.notes.count())
        ]
        ws.append(row)
        # apply borders to last row
        r = ws.max_row
        for c in range(1, len(headers)+1):
            ws.cell(row=r, column=c).border = border

    # Column widths and number formats
    from openpyxl.utils import get_column_letter
    widths = [6, 8, 10, 18, 18, 14, 12, 8, 24, 10, 12, 26, 12, 24, 8, 10, 10, 10, 8, 10, 10, 10, 10, 10, 12, 12, 12, 12, 14, 14, 14, 14, 14, 14, 30]
    for i in range(1, len(headers) + 1):
        try:
            w = widths[i-1] if i-1 < len(widths) else 12
            ws.column_dimensions[get_column_letter(i)].width = w
        except Exception:
            pass
    currency_fmt = '[$$-409]#,##0.00'
    for row in ws.iter_rows(min_row=5, min_col=1, max_col=len(headers), max_row=ws.max_row):
        for idx, cell in enumerate(row, start=1):
            if idx in money_cols and isinstance(cell.value, (int, float)):
                cell.number_format = currency_fmt

    ws.freeze_panes = 'A5'

    # Build response
    from io import BytesIO
    buff = BytesIO()
    wb.save(buff)
    buff.seek(0)

    response = HttpResponse(
        buff.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="contract_log.xlsx"'

    # Timing record
    end_time = time.time()
    ExportTiming.objects.create(
        row_count=clins.count(),
        export_time=(end_time - start_time),
        filters_applied={'format': 'xlsx'}
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
