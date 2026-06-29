"""Backfill matched_contract on DibbsAwardMod by iterating contracts in DB."""

from collections import defaultdict

from django.db import migrations


def backfill_matched_contract(apps, schema_editor):
    from contracts.models import Contract
    from contracts.services.contract_number import normalize_contract_number
    from sales.models import DibbsAwardMod
    from sales.services.contract_mods import match_dibbs_award_mod, mod_contract_identity

    by_identity: dict[str, list[int]] = defaultdict(list)
    for mod in (
        DibbsAwardMod.objects.filter(matched_contract__isnull=True)
        .only(
            "id",
            "award_basic_number",
            "delivery_order_number",
            "matched_contract_id",
        )
        .iterator(chunk_size=500)
    ):
        raw = mod_contract_identity(mod)
        if not raw:
            continue
        key = normalize_contract_number(raw)
        if key:
            by_identity[key].append(mod.id)

    matched_ids: set[int] = set()
    for contract in Contract.objects.only("id", "contract_number").iterator(
        chunk_size=200
    ):
        target = normalize_contract_number(contract.contract_number)
        if not target:
            continue
        for mod_id in by_identity.get(target, ()):
            if mod_id in matched_ids:
                continue
            mod = DibbsAwardMod.objects.get(pk=mod_id)
            if match_dibbs_award_mod(mod):
                matched_ids.add(mod_id)


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0051_dibbs_award_mod_contract_match_ack"),
    ]

    operations = [
        migrations.RunPython(backfill_matched_contract, migrations.RunPython.noop),
    ]
