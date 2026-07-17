"""Shared read-only context builder for contract split breakdowns."""

from decimal import Decimal

from contracts.models import ClinSplit, ContractLevelCharge, ContractPackaging


def build_split_breakdown_context(contract):
    """Build the per-company split reconciliation context for a contract."""
    clin_splits_by_company = {}
    for split in ClinSplit.objects.filter(
        clin__contract=contract
    ).select_related('clin').prefetch_related(
        'clin__finance_lines'
    ).order_by('company_name', 'clin__item_number'):
        cname = split.company_name
        if cname not in clin_splits_by_company:
            clin_splits_by_company[cname] = []

        clin = split.clin
        wawf_val = Decimal(str(clin.wawf_payment or 0))
        item_val = Decimal(str(clin.item_value or 0))
        income = wawf_val if wawf_val != Decimal('0') else item_val
        quote_val = Decimal(str(clin.quote_value or 0))
        paid_val = Decimal(str(clin.paid_amount or 0))
        cost = paid_val if paid_val != Decimal('0') else quote_val
        gross = income - cost
        fin_costs = sum(
            Decimal(str(fl.amount_billed or 0))
            for fl in clin.finance_lines.all()
        )
        clin_raw_gp = gross - fin_costs
        pct = split.percentage
        if pct is not None:
            raw_split_value = (
                clin_raw_gp * pct / Decimal('100')
            ).quantize(Decimal('0.01'))
        else:
            raw_split_value = None

        clin_splits_by_company[cname].append({
            'split_id': split.id,
            'item_number': clin.item_number,
            'split_value': split.split_value,
            'split_paid': split.split_paid,
            'percentage': pct,
            'raw_split_value': raw_split_value,
        })

    # Use the first non-null percentage found per company for summary display.
    company_percentages = {}
    for cname, rows in clin_splits_by_company.items():
        for row in rows:
            if row['percentage'] is not None:
                company_percentages[cname] = row['percentage']
                break

    packaging_deduction = Decimal('0.00')
    packaging_context = None
    try:
        pkg = contract.packaging
        if (
            pkg.amount_paid is not None
            and Decimal(str(pkg.amount_paid)) != Decimal('0')
        ):
            packaging_deduction = Decimal(str(pkg.amount_paid))
        elif (
            pkg.quote_amount is not None
            and Decimal(str(pkg.quote_amount)) != Decimal('0')
        ):
            packaging_deduction = Decimal(str(pkg.quote_amount))
        packaging_context = pkg
    except ContractPackaging.DoesNotExist:
        pass

    packaging_share_per_company = {}
    if packaging_deduction:
        for company_name, rows in clin_splits_by_company.items():
            pct = next(
                (r['percentage'] for r in rows if r['percentage'] is not None),
                None,
            )
            if pct is not None:
                packaging_share_per_company[company_name] = (
                    packaging_deduction * pct / Decimal('100')
                ).quantize(Decimal('0.01'))

    charges_deduction = Decimal('0.00')
    level_charges = list(
        contract.level_charges.select_related('supplier').order_by('id')
    )
    for charge in level_charges:
        if (
            charge.billed_paid_amount is not None
            and Decimal(str(charge.billed_paid_amount)) != Decimal('0')
        ):
            charges_deduction += Decimal(str(charge.billed_paid_amount))
        else:
            charges_deduction += Decimal(str(charge.estimated_amount))

    # Per-company itemized ContractLevelCharge shares for the split accordion.
    level_charge_shares_per_company = {}
    if level_charges:
        for company_name, rows in clin_splits_by_company.items():
            pct = next(
                (r['percentage'] for r in rows if r['percentage'] is not None),
                None,
            )
            if pct is None:
                continue
            charge_rows = []
            for charge in level_charges:
                if (
                    charge.billed_paid_amount is not None
                    and Decimal(str(charge.billed_paid_amount)) != Decimal('0')
                ):
                    amount = Decimal(str(charge.billed_paid_amount))
                else:
                    amount = Decimal(str(charge.estimated_amount))
                share = (
                    amount * pct / Decimal('100')
                ).quantize(Decimal('0.01'))
                if share == Decimal('0.00'):
                    continue
                charge_rows.append({
                    'label': charge.label,
                    'supplier_name': (
                        charge.supplier.name if charge.supplier_id else None
                    ),
                    'share': share,
                })
            if charge_rows:
                level_charge_shares_per_company[company_name] = charge_rows

    return {
        'clin_splits_by_company': clin_splits_by_company,
        'company_percentages': company_percentages,
        'packaging': packaging_context,
        'packaging_deduction': packaging_deduction,
        'packaging_share_per_company': packaging_share_per_company,
        'level_charges': level_charges,
        'charges_deduction': charges_deduction,
        'level_charge_shares_per_company': level_charge_shares_per_company,
    }
