"""Backfill matched_contract on DibbsAwardMod by iterating contracts in DB."""

from collections import defaultdict

from django.db import migrations, transaction


def backfill_matched_contract(apps, schema_editor):
    # MSSQL FIX: Materialize ALL querysets into Python lists/dicts BEFORE any
    # secondary DB reads or writes. pyodbc (no MARS) cannot hold an open
    # server-side cursor from .iterator() while another command runs on the
    # same connection — e.g. DibbsAwardMod.objects.get() inside a contract loop.
    from contracts.models import Contract
    from contracts.services.contract_number import canonicalize_contract_number
    from sales.models import DibbsAwardMod
    from sales.services.contract_mods import mod_contract_identity

    unmatched_mods = list(
        DibbsAwardMod.objects.filter(matched_contract__isnull=True).only(
            "id",
            "award_basic_number",
            "delivery_order_number",
            "matched_contract_id",
        )
    )
    mods_by_id = {mod.id: mod for mod in unmatched_mods}

    by_identity: dict[str, list[int]] = defaultdict(list)
    for mod in unmatched_mods:
        raw = mod_contract_identity(mod)
        if not raw:
            continue
        key = canonicalize_contract_number(raw)
        if key:
            by_identity[key].append(mod.id)

    contracts = list(
        Contract.objects.all().values("id", "contract_number")
    )

    contracts_by_normalized: dict[str, list[int]] = defaultdict(list)
    for contract in contracts:
        target = canonicalize_contract_number(contract["contract_number"])
        if target:
            contracts_by_normalized[target].append(contract["id"])

    unique_contract_by_normalized = {
        key: ids[0] for key, ids in contracts_by_normalized.items() if len(ids) == 1
    }

    matched_ids: set[int] = set()
    mods_to_update: list[DibbsAwardMod] = []

    for contract in contracts:
        target = canonicalize_contract_number(contract["contract_number"])
        if not target:
            continue
        contract_pk = unique_contract_by_normalized.get(target)
        if contract_pk is None:
            continue
        for mod_id in by_identity.get(target, ()):
            if mod_id in matched_ids:
                continue
            mod = mods_by_id.get(mod_id)
            if mod is None or mod.matched_contract_id is not None:
                continue
            # Same semantics as match_dibbs_award_mod: exact unique Contract match only.
            mod.matched_contract_id = contract_pk
            mods_to_update.append(mod)
            matched_ids.add(mod_id)

    if not mods_to_update:
        return

    with transaction.atomic():
        batch_size = 500
        for i in range(0, len(mods_to_update), batch_size):
            DibbsAwardMod.objects.bulk_update(
                mods_to_update[i : i + batch_size],
                ["matched_contract"],
                batch_size=batch_size,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0051_dibbs_award_mod_contract_match_ack"),
    ]

    operations = [
        migrations.RunPython(backfill_matched_contract, migrations.RunPython.noop),
    ]
