from decimal import Decimal
from django.db import models
from django.db.models import Sum
from contracts.models import Contract, ClinSplit, PartnerReconciliation, PartnerReconciliationRow
from contracts.utils.excel_utils import load_workbook
from decimal import Decimal, InvalidOperation
from django.db import transaction

def _safe_decimal(value):
    """
    Convert an Excel cell value to Decimal safely.
    Handles None, empty strings, currency symbols, commas,
    dashes, and any non-numeric text. Returns None on failure.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Reject known non-numeric placeholders
    if s.upper() in ('-', 'N/A', '#N/A', '#VALUE!', '#REF!', '—', '–', 'TBD', 'NA'):
        return None
    # Strip currency formatting
    s = s.replace('$', '').replace(',', '').strip()
    # Handle parenthetical negatives like (1234.56)
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None

def to_decimal(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    # Clean string
    val_str = str(value).strip().replace('$', '').replace(',', '')
    if not val_str:
        return None
    try:
        return Decimal(val_str)
    except Exception:
        return None

def parse_ppi_excel(file_obj):
    """
    Parses PPI-specific 3-tab Excel commission report.
    Returns a list of raw row dicts.
    """
    wb = load_workbook()(file_obj, read_only=True, data_only=True)
    raw_rows = []
    
    known_tabs = ['TO BE PAID', 'PAID TO MSC', 'MISSING INFORMATION']
    
    for sheet in wb.worksheets:
        sheet_name = sheet.title.strip().upper()
        if sheet_name not in known_tabs:
            continue
            
        header_row_idx = None
        # Scan first 5 rows to find 'CONTRACT #'
        # We can read up to 5 rows using iter_rows
        rows_preview = list(sheet.iter_rows(max_row=5, values_only=False))
        for r_idx, row in enumerate(rows_preview):
            found_header = False
            for cell in row:
                if cell.value and str(cell.value).strip().upper() == 'CONTRACT #':
                    header_row_idx = r_idx + 1
                    found_header = True
                    break
            if found_header:
                break
                
        if not header_row_idx:
            continue
            
        # Extract headers from the header row
        header_row = rows_preview[header_row_idx - 1]
        col_map = {}
        for c_idx, cell in enumerate(header_row):
            if cell.value is not None:
                val_clean = str(cell.value).strip().upper()
                if val_clean == 'CONTRACT #':
                    col_map['contract_number'] = c_idx
                elif val_clean == 'PURCHASE ORDER':
                    col_map['po_number'] = c_idx
                elif val_clean == 'AWARD $':
                    col_map['award_amount'] = c_idx
                elif val_clean == 'MSC/PPI':
                    col_map['commission_amount'] = c_idx
                    
        if 'contract_number' not in col_map:
            continue
            
        # Parse data rows starting from the row after the header row
        for row in sheet.iter_rows(min_row=header_row_idx + 1, values_only=False):
            # Check if we have enough elements in row
            contract_idx = col_map['contract_number']
            if contract_idx >= len(row):
                continue
                
            contract_cell_val = row[contract_idx].value
            if contract_cell_val is None:
                continue
                
            contract_number = str(contract_cell_val).strip()
            if not contract_number:
                continue
                
            # Extract other values
            po_number = ""
            po_idx = col_map.get('po_number')
            if po_idx is not None and po_idx < len(row) and row[po_idx].value is not None:
                po_number = str(row[po_idx].value).strip()
                
            award_amount = None
            award_idx = col_map.get('award_amount')
            if award_idx is not None and award_idx < len(row):
                award_amount = _safe_decimal(row[award_idx].value)
                
            commission_amount = None
            comm_idx = col_map.get('commission_amount')
            if comm_idx is not None and comm_idx < len(row):
                commission_amount = _safe_decimal(row[comm_idx].value)
                
            raw_rows.append({
                'contract_number': contract_number,
                'po_number': po_number,
                'award_amount': award_amount,
                'commission_amount': commission_amount,
                'tab': sheet_name,
            })
            
    return raw_rows

def reconcile_partner(partner_name, raw_rows, company, uploaded_by, filename, notes):
    """
    Core reconciliation logic that compares raw partner rows against STATZ's ClinSplit records.
    """
    with transaction.atomic():
        # Step 1 — Build lookup of all contracts in our DB that have splits for this partner
        partner_splits_qs = (
            ClinSplit.objects
            .filter(
                clin__contract__company=company,
                company_name__iexact=partner_name,
            )
            .values('clin__contract__id', 'clin__contract__contract_number')
            .annotate(
                total_split_value=Sum('split_value'),
                total_split_paid=Sum('split_paid'),
            )
            .order_by()
        )
        statz_by_contract_number = {
            row['clin__contract__contract_number'].strip().upper(): row
            for row in partner_splits_qs
        }

        # Step 2 — Also build a lookup of Contract objects by contract_number for FK assignment
        contracts_by_number = {
            c.contract_number.strip().upper(): c
            for c in Contract.objects.filter(company=company)
        }

        # Step 3 — Create the PartnerReconciliation header record (save first to get PK for rows)
        reconciliation = PartnerReconciliation(
            company=company,
            partner_name=partner_name,
            uploaded_by=uploaded_by,
            filename=filename,
            notes=notes,
        )
        reconciliation.save()

        rows_to_create = []
        processed_contract_numbers = set()

        # Step 4 — Process each row from raw_rows
        for raw_row in raw_rows:
            lookup_key = raw_row['contract_number'].strip().upper()
            statz_data = statz_by_contract_number.get(lookup_key)
            contract_obj = contracts_by_number.get(lookup_key)

            if statz_data is None and contract_obj is None:
                status = PartnerReconciliationRow.STATUS_MISSING_IN_STATZ
                statz_split_value = None
                statz_split_paid = None
                amount_variance = None
            else:
                if statz_data is not None:
                    statz_split_value = statz_data['total_split_value']
                    statz_split_paid = statz_data['total_split_paid']
                else:
                    statz_split_value = None
                    statz_split_paid = None

                partner_commission = raw_row['commission_amount']
                if partner_commission is not None and statz_split_value is not None:
                    amount_variance = partner_commission - statz_split_value
                else:
                    amount_variance = None

                # Status determination (evaluated in priority order, first match wins):
                if amount_variance is not None and abs(amount_variance) > Decimal('0.01'):
                    status = PartnerReconciliationRow.STATUS_AMOUNT_DISCREPANCY
                elif raw_row['tab'] == 'PAID TO MSC' and (statz_split_paid is None or statz_split_paid == 0):
                    status = PartnerReconciliationRow.STATUS_PAYMENT_DISCREPANCY
                elif (raw_row['tab'] == 'TO BE PAID' and
                    statz_split_paid is not None and
                    statz_split_value is not None and
                    statz_split_paid >= statz_split_value):
                    status = PartnerReconciliationRow.STATUS_PAYMENT_DISCREPANCY
                else:
                    status = PartnerReconciliationRow.STATUS_MATCH

            processed_contract_numbers.add(lookup_key)

            rows_to_create.append(PartnerReconciliationRow(
                reconciliation=reconciliation,
                contract=contract_obj,
                partner_contract_number=raw_row['contract_number'],
                partner_po_number=raw_row['po_number'],
                partner_award_amount=raw_row['award_amount'],
                partner_commission_amount=raw_row['commission_amount'],
                partner_tab=raw_row['tab'],
                statz_split_value=statz_split_value,
                statz_split_paid=statz_split_paid,
                status=status,
                amount_variance=amount_variance,
            ))

        # Step 5 — Find missing_in_partner rows
        for key, statz_data in statz_by_contract_number.items():
            if key not in processed_contract_numbers:
                db_contract_number = statz_data['clin__contract__contract_number']
                contract_obj = contracts_by_number.get(key)

                rows_to_create.append(PartnerReconciliationRow(
                    reconciliation=reconciliation,
                    contract=contract_obj,
                    partner_contract_number=db_contract_number,
                    partner_po_number='',
                    partner_award_amount=None,
                    partner_commission_amount=None,
                    partner_tab='',
                    statz_split_value=statz_data['total_split_value'],
                    statz_split_paid=statz_data['total_split_paid'],
                    status=PartnerReconciliationRow.STATUS_MISSING_IN_PARTNER,
                    amount_variance=None,
                ))

        # Step 6 — Bulk create all rows, compute summary counts, save reconciliation
        if rows_to_create:
            PartnerReconciliationRow.objects.bulk_create(rows_to_create)

        # Calculate summary counts
        total_partner_rows = 0
        matched_count = 0
        amount_discrepancy_count = 0
        payment_discrepancy_count = 0
        missing_in_statz_count = 0
        missing_in_partner_count = 0

        for row in rows_to_create:
            if row.status != PartnerReconciliationRow.STATUS_MISSING_IN_PARTNER:
                total_partner_rows += 1

            if row.status == PartnerReconciliationRow.STATUS_MATCH:
                matched_count += 1
            elif row.status == PartnerReconciliationRow.STATUS_AMOUNT_DISCREPANCY:
                amount_discrepancy_count += 1
            elif row.status == PartnerReconciliationRow.STATUS_PAYMENT_DISCREPANCY:
                payment_discrepancy_count += 1
            elif row.status == PartnerReconciliationRow.STATUS_MISSING_IN_STATZ:
                missing_in_statz_count += 1
            elif row.status == PartnerReconciliationRow.STATUS_MISSING_IN_PARTNER:
                missing_in_partner_count += 1

        reconciliation.total_partner_rows = total_partner_rows
        reconciliation.matched_count = matched_count
        reconciliation.amount_discrepancy_count = amount_discrepancy_count
        reconciliation.payment_discrepancy_count = payment_discrepancy_count
        reconciliation.missing_in_statz_count = missing_in_statz_count
        reconciliation.missing_in_partner_count = missing_in_partner_count
        reconciliation.save()

        return reconciliation
