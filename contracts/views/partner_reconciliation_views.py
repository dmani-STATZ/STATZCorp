from django.views import View
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseForbidden, Http404
from django.utils.decorators import method_decorator
from django.db.models import Count
from STATZWeb.decorators import conditional_login_required

from ..models import PartnerReconciliation, PartnerReconciliationRow
from ..forms import PartnerReconciliationForm
from ..services.partner_reconciliation import parse_ppi_excel, reconcile_partner
from contracts.utils.excel_utils import Workbook, get_column_letter, PatternFill, Font, Alignment

@method_decorator(conditional_login_required, name="dispatch")
class PartnerReconciliationListView(View):
    def get(self, request, *args, **kwargs):
        company = getattr(request, 'active_company', None)
        if not company:
            return HttpResponseForbidden("No active company set")
            
        reconciliations = PartnerReconciliation.objects.filter(company=company).order_by('-uploaded_at')
        form = PartnerReconciliationForm(company=company)
        
        context = {
            'reconciliations': reconciliations,
            'form': form,
        }
        return render(request, 'contracts/partner_reconciliation_list.html', context)

    def post(self, request, *args, **kwargs):
        company = getattr(request, 'active_company', None)
        if not company:
            return HttpResponseForbidden("No active company set")
            
        reconciliations = PartnerReconciliation.objects.filter(company=company).order_by('-uploaded_at')
        form = PartnerReconciliationForm(request.POST, request.FILES, company=company)
        
        if form.is_valid():
            partner_name = form.cleaned_data['partner_name']
            excel_file = request.FILES['excel_file']
            notes = form.cleaned_data.get('notes', '')
            
            try:
                raw_rows = parse_ppi_excel(excel_file)
                reconciliation = reconcile_partner(
                    partner_name=partner_name,
                    raw_rows=raw_rows,
                    company=company,
                    uploaded_by=request.user,
                    filename=excel_file.name,
                    notes=notes,
                )
                return redirect('contracts:partner_reconciliation_detail', pk=reconciliation.pk)
            except Exception as e:
                form.add_error(None, f"An error occurred during reconciliation: {e}")
                
        context = {
            'reconciliations': reconciliations,
            'form': form,
        }
        return render(request, 'contracts/partner_reconciliation_list.html', context)


@method_decorator(conditional_login_required, name="dispatch")
class PartnerReconciliationDetailView(View):
    def get(self, request, pk, *args, **kwargs):
        company = getattr(request, 'active_company', None)
        if not company:
            return HttpResponseForbidden("No active company set")
            
        reconciliation = get_object_or_404(
            PartnerReconciliation.objects.filter(company=company),
            pk=pk
        )
        
        status_filter = request.GET.get('status', '').strip()
        rows = reconciliation.rows.all()
        
        valid_statuses = [choice[0] for choice in PartnerReconciliationRow.STATUS_CHOICES]
        if status_filter in valid_statuses:
            rows = rows.filter(status=status_filter)
        else:
            status_filter = ''
            
        # Get status counts
        counts = reconciliation.rows.values('status').annotate(count=Count('id')).order_by()
        status_counts = {choice[0]: 0 for choice in PartnerReconciliationRow.STATUS_CHOICES}
        for item in counts:
            status_counts[item['status']] = item['count']
            
        status_counts['all'] = reconciliation.rows.count()
        
        context = {
            'reconciliation': reconciliation,
            'rows': rows,
            'status_filter': status_filter,
            'status_counts': status_counts,
            'STATUS_CHOICES': PartnerReconciliationRow.STATUS_CHOICES,
        }
        return render(request, 'contracts/partner_reconciliation_detail.html', context)


@method_decorator(conditional_login_required, name="dispatch")
class PartnerReconciliationExportView(View):
    def get(self, request, pk, *args, **kwargs):
        company = getattr(request, 'active_company', None)
        if not company:
            return HttpResponseForbidden("No active company set")
            
        reconciliation = get_object_or_404(
            PartnerReconciliation.objects.filter(company=company),
            pk=pk
        )
        
        # Instantiate Workbook
        wb = Workbook()()  # Note the double parentheses from excel_utils wrapper
        ws = wb.active
        ws.title = f"{reconciliation.partner_name} Reconciliation"[:31]
        
        # Merge cells for title blocks
        ws.merge_cells("A1:H1")
        ws["A1"] = "Partner Commission Reconciliation"
        ws["A1"].font = Font()(bold=True, size=14)
        ws["A1"].alignment = Alignment()(horizontal="center")
        
        ws.merge_cells("A2:H2")
        uploaded_by_str = str(reconciliation.uploaded_by) if reconciliation.uploaded_by else "System"
        ws["A2"] = f"Partner: {reconciliation.partner_name}  |  Uploaded: {reconciliation.uploaded_at:%Y-%m-%d}  |  By: {uploaded_by_str}"
        ws["A2"].font = Font()(italic=True)
        ws["A2"].alignment = Alignment()(horizontal="center")
        
        # Row 3 is blank
        
        # Header Row at Row 4
        headers = [
            "Status", "Contract #", "PO Number", "Partner Tab", 
            "Partner Amount", "STATZ Split Value", "STATZ Split Paid", "Amount Variance"
        ]
        header_fill = PatternFill()(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=4, column=col_idx, value=header)
            cell.font = Font()(bold=True)
            cell.fill = header_fill
            
        # Fills for status coloring
        fills = {
            'match': PatternFill()(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),
            'amount_discrepancy': PatternFill()(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),
            'payment_discrepancy': PatternFill()(start_color="FFCC99", end_color="FFCC99", fill_type="solid"),
            'missing_in_statz': PatternFill()(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
            'missing_in_partner': PatternFill()(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid"),
        }
        
        current_row = 5
        rows = reconciliation.rows.all().order_by('status', 'partner_contract_number')
        for r in rows:
            ws.cell(row=current_row, column=1, value=r.get_status_display())
            ws.cell(row=current_row, column=2, value=r.partner_contract_number)
            ws.cell(row=current_row, column=3, value=r.partner_po_number)
            ws.cell(row=current_row, column=4, value=r.partner_tab)
            
            # Numeric fields
            ws.cell(row=current_row, column=5, value=r.partner_commission_amount)
            ws.cell(row=current_row, column=6, value=r.statz_split_value)
            ws.cell(row=current_row, column=7, value=r.statz_split_paid)
            ws.cell(row=current_row, column=8, value=r.amount_variance)
            
            # Colors
            status_cell = ws.cell(row=current_row, column=1)
            if r.status in fills:
                status_cell.fill = fills[r.status]
                
            # Formatting for dollar fields
            for col_idx in [5, 6, 7, 8]:
                c = ws.cell(row=current_row, column=col_idx)
                if c.value is not None:
                    c.number_format = '$#,##0.00'
                    
            current_row += 1
            
        # Auto-size columns
        for col_idx in range(1, 9):
            col_letter = get_column_letter()(col_idx)
            max_len = 0
            for row_idx in range(4, current_row):
                cell_val = ws.cell(row=row_idx, column=col_idx).value
                if cell_val is not None:
                    # Format float/decimal values to show length of estimated string
                    if isinstance(cell_val, (int, float, Decimal)):
                        val_str = f"${cell_val:,.2f}"
                    else:
                        val_str = str(cell_val)
                    max_len = max(max_len, len(val_str))
            ws.column_dimensions[col_letter].width = max(min(max_len + 2, 40), 10)
            
        # Return response
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        partner_slug = reconciliation.partner_name.replace(' ', '_').replace('/', '_')
        date_str = reconciliation.uploaded_at.strftime('%Y%m%d')
        response['Content-Disposition'] = f'attachment; filename="{partner_slug}_{date_str}_reconciliation.xlsx"'
        wb.save(response)
        return response
