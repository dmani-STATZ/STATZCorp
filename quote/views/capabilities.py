"""
Supplier capability screens: the Capabilities page, the per-supplier editor
(an HTML fragment shown in a drawer here and inline on the supplier page), and
the paste / file import behind both.

Views orchestrate only -- parsing, planning, committing and pruning matches all
live in quote/services/capabilities.py.
"""
import csv
import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from quote.models import (
    QuoteCapabilityImport,
    QuoteSupplierFSC,
    QuoteSupplierNSN,
)
from quote.services.capabilities import (
    CapabilityError,
    Mapping,
    build_plan,
    capability_overview,
    clean_keys,
    commit_plan,
    export_rows,
    linked_open_solicitations,
    plan_to_preview,
    read_text,
    read_upload,
    remove_capabilities,
    undo_import,
)
from quote.services.queue import status_counts
from suppliers.models import Supplier

EDITOR_PAGE_SIZE = 50
MAX_REMOVE = 5000


def _is_xhr(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def _bad(message, status=400):
    return JsonResponse({'error': message}, status=status)


# ── Pages ────────────────────────────────────────────────────────────────────

@login_required
@require_GET
def capabilities(request):
    """GET /quote/capabilities/ -- who can supply what, plus recent imports."""
    rows, totals = capability_overview()
    open_supplier = None
    if (request.GET.get('supplier') or '').isdigit():
        open_supplier = Supplier.objects.filter(pk=int(request.GET['supplier'])).first()
    return render(request, 'quote/capabilities/index.html', {
        'section': 'capabilities',
        'rows': rows,
        'totals': totals,
        'unmatched_open': status_counts().get('UNMATCHED', 0),
        'recent_imports': list(
            QuoteCapabilityImport.objects.select_related('created_by', 'supplier')[:10]
        ),
        'open_supplier': open_supplier,
    })


@login_required
@require_GET
def capability_import_page(request):
    """GET /quote/capabilities/import/ -- import pairings for one or many suppliers."""
    preset = None
    if (request.GET.get('supplier') or '').isdigit():
        preset = Supplier.objects.filter(pk=int(request.GET['supplier']), archived=False).first()
    return render(request, 'quote/capabilities/import.html', {
        'section': 'capabilities',
        'preset_supplier': preset,
    })


@login_required
@require_GET
def capability_supplier(request, supplier_id):
    """
    GET /quote/capabilities/supplier/<id>/ -- the editor fragment for one
    supplier. Opened directly (not by XHR) it lands on the Capabilities page
    with that supplier's drawer open.
    """
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    if not _is_xhr(request):
        return redirect(f"{reverse('quote:capabilities')}?supplier={supplier.pk}")

    query = (request.GET.get('q') or '').strip()
    nsns = QuoteSupplierNSN.objects.filter(supplier=supplier)
    if query:
        match = Q(notes__icontains=query)
        digits = ''.join(ch for ch in query if ch.isdigit())
        if digits:
            match |= Q(nsn__contains=digits)
        nsns = nsns.filter(match)
    nsns = nsns.select_related('added_by', 'import_batch').order_by('-added_at', '-pk')
    page = Paginator(nsns, EDITOR_PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'quote/capabilities/_editor.html', {
        'supplier': supplier,
        'fscs': list(
            QuoteSupplierFSC.objects.filter(supplier=supplier)
            .select_related('added_by', 'import_batch').order_by('fsc')
        ),
        'nsn_page': page,
        'nsn_total': QuoteSupplierNSN.objects.filter(supplier=supplier).count(),
        'query': query,
        'linked_open': linked_open_solicitations(supplier),
    })


# ── Import: preview and commit share one payload ─────────────────────────────

def _read_payload(request):
    """
    ``(table, supplier | None, mapping | None, assignments)`` from a preview /
    commit POST: pasted ``text`` or an uploaded ``file``, an optional fixed
    ``supplier_id``, the column ``mapping`` and per-supplier ``assignments``.
    """
    supplier = None
    raw_supplier = (request.POST.get('supplier_id') or '').strip()
    if raw_supplier:
        supplier = Supplier.objects.filter(pk=raw_supplier, archived=False).first() \
            if raw_supplier.isdigit() else None
        if supplier is None:
            raise CapabilityError("That supplier isn't available. Pick another.")

    upload = request.FILES.get('file')
    text = request.POST.get('text') or ''
    if upload is not None:
        table = read_upload(upload)
    elif text.strip():
        table = read_text(text)
    else:
        raise CapabilityError('Paste a list or drop a file first.')

    try:
        mapping = Mapping.from_payload(json.loads(request.POST.get('mapping') or 'null'), table.width)
        assignments = json.loads(request.POST.get('assignments') or '{}')
    except ValueError:
        raise CapabilityError('That request was garbled. Reload the page and try again.')
    if not isinstance(assignments, dict):
        assignments = {}
    return table, supplier, mapping, assignments


@login_required
@require_POST
def capability_import_preview(request):
    """POST -- dry run: what an import would add, skip and do to open solicitations."""
    try:
        table, supplier, mapping, assignments = _read_payload(request)
        plan = build_plan(table, supplier=supplier, mapping=mapping, assignments=assignments)
    except CapabilityError as exc:
        return _bad(str(exc))
    return JsonResponse(plan_to_preview(plan))


@login_required
@require_POST
def capability_import_commit(request):
    """POST -- run the import (same payload as the preview) and re-match solicitations."""
    try:
        table, supplier, mapping, assignments = _read_payload(request)
        plan = build_plan(
            table, supplier=supplier, mapping=mapping, assignments=assignments,
            with_impact=False,
        )
        batch = commit_plan(plan, request.user, supplier=supplier)
    except CapabilityError as exc:
        return _bad(str(exc))
    return JsonResponse({
        'ok': True,
        'import_id': batch.pk,
        'nsns_added': batch.nsns_added,
        'fscs_added': batch.fscs_added,
        'already_on_file': batch.nsns_existing + batch.fscs_existing,
        'suppliers': batch.suppliers_touched,
        'matches_created': batch.matches_created,
        'solicitations_matched': batch.solicitations_matched,
        'undo_url': reverse('quote:capability_import_undo', args=[batch.pk]),
    })


@login_required
@require_POST
def capability_import_undo(request, import_id):
    """POST -- take back everything one import added."""
    batch = get_object_or_404(QuoteCapabilityImport, pk=import_id)
    try:
        result = undo_import(batch, request.user)
    except CapabilityError as exc:
        return _bad(str(exc), status=409)
    return JsonResponse({'ok': True, **result})


# ── Editing one supplier ─────────────────────────────────────────────────────

@login_required
@require_POST
def capability_remove(request, supplier_id):
    """POST JSON {nsns: [...], fscs: [...]} -- remove capabilities from a supplier."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    try:
        payload = json.loads(request.body or b'{}')
    except ValueError:
        return _bad('That request was garbled. Reload the page and try again.')
    nsns = payload.get('nsns') or []
    fscs = payload.get('fscs') or []
    if not isinstance(nsns, list) or not isinstance(fscs, list):
        return _bad('Send lists of NSNs and FSCs.')
    if not (nsns or fscs):
        return _bad('Pick something to remove.')
    if len(nsns) + len(fscs) > MAX_REMOVE:
        return _bad(f'Remove at most {MAX_REMOVE:,} at a time.')
    nsn_set, fsc_set = clean_keys(nsns, fscs)
    if not (nsn_set or fsc_set):
        return _bad("None of those look like NSNs or FSCs.")
    result = remove_capabilities(supplier, nsn_set, fsc_set)
    return JsonResponse({'ok': True, **result})


# ── Export ───────────────────────────────────────────────────────────────────

class _Echo:
    def write(self, value):
        return value


def _safe_cell(value):
    """Stop spreadsheet apps treating a text cell as a formula."""
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


@login_required
@require_GET
def capability_export(request):
    """GET /quote/capabilities/export/[?supplier=<id>] -- every pairing as CSV (re-importable)."""
    supplier = None
    stem = 'supplier-capabilities'
    if (request.GET.get('supplier') or '').isdigit():
        supplier = get_object_or_404(Supplier, pk=int(request.GET['supplier']))
        if supplier.cage_code:
            stem += f'-{supplier.cage_code}'
    writer = csv.writer(_Echo())

    def lines():
        yield '﻿'   # BOM so Excel reads UTF-8
        for row in export_rows(supplier):
            yield writer.writerow([_safe_cell(cell) for cell in row])

    response = StreamingHttpResponse(lines(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = (
        f'attachment; filename="{stem}-{timezone.now():%Y%m%d}.csv"'
    )
    return response
