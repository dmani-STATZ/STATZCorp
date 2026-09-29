"""
Phase 3 screens: Bid Board (staging + side-by-side quote comparison), the bid
builder, and the DIBBS BQ export. Views orchestrate; quote/services/bids.py
owns defaults, pre-flight and the file writer.
"""
from collections import OrderedDict
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from dibbs.models import Solicitation
from quote.models import QuoteBid, QuoteSupplierQuote
from quote.services import bids as bid_service
from quote.services import cost

SUBMITTED_HISTORY_DAYS = 60


def _is_xhr(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


# ── Bid Board ────────────────────────────────────────────────────────────────

def _board_rows(today):
    """One row per open solicitation that has at least one supplier quote."""
    quotes = (
        QuoteSupplierQuote.objects.filter(line__solicitation__return_by_date__gte=today)
        .select_related('supplier', 'line__solicitation')
        .order_by('line__solicitation__return_by_date', 'line__solicitation__solicitation_number',
                  'line__line_number')
    )
    rows = OrderedDict()
    for q in quotes:
        sol = q.line.solicitation
        row = rows.setdefault(sol.pk, {'solicitation': sol, 'lines': OrderedDict()})
        entry = row['lines'].setdefault(q.line_id, {
            'line': q.line, 'quotes': 0, 'selected': None, 'auto': False, 'bid': None,
        })
        entry['quotes'] += 1
        if q.is_selected_for_bid:
            entry['selected'] = q
            entry['auto'] = q.selected_automatically
    line_ids = [lid for row in rows.values() for lid in row['lines']]
    for bid in QuoteBid.objects.filter(line_id__in=line_ids):
        for row in rows.values():
            if bid.line_id in row['lines']:
                row['lines'][bid.line_id]['bid'] = bid
    for row in rows.values():
        statuses = {e['bid'].bid_status if e['bid'] else '' for e in row['lines'].values()}
        row['status'] = (
            'SUBMITTED' if statuses == {QuoteBid.STATUS_SUBMITTED}
            else 'READY' if statuses <= {QuoteBid.STATUS_READY, QuoteBid.STATUS_SUBMITTED}
            else 'DRAFT' if QuoteBid.STATUS_DRAFT in statuses or QuoteBid.STATUS_READY in statuses
            else 'NONE'
        )
        row['line_list'] = list(row['lines'].values())
        row['days_left'] = (row['solicitation'].return_by_date - today).days
        row['auto_award'] = bid_service.is_auto_award(row['solicitation'].solicitation_number)
    return list(rows.values())


@login_required
def bid_board(request):
    """GET /quote/bids/?tab=needs|ready|submitted"""
    today = timezone.now().date()
    tab = request.GET.get('tab', 'needs')
    rows = _board_rows(today)
    counts = {
        'needs': sum(1 for r in rows if r['status'] in ('NONE', 'DRAFT')),
        'ready': sum(1 for r in rows if r['status'] == 'READY'),
    }
    exports = (
        QuoteBid.objects.filter(
            bid_status=QuoteBid.STATUS_SUBMITTED,
            submitted_at__gte=timezone.now() - timedelta(days=SUBMITTED_HISTORY_DAYS),
        ).exclude(exported_bq_file='')
        .values('exported_bq_file', 'submitted_by__username', 'submitted_by__first_name',
                'submitted_by__last_name')
        .annotate(bids=Count('id'), sols=Count('line__solicitation', distinct=True))
        .order_by('-exported_bq_file')
    )
    counts['submitted'] = len(exports)
    if tab == 'ready':
        shown = [r for r in rows if r['status'] == 'READY']
    elif tab == 'submitted':
        shown = []
    else:
        tab = 'needs'
        shown = [r for r in rows if r['status'] in ('NONE', 'DRAFT')]
    return render(request, 'quote/bids/board.html', {
        'section': 'bids',
        'tab': tab,
        'rows': shown,
        'counts': counts,
        'exports': exports,
        # Open solicitations that have quotes but whose bids all went to DIBBS already: the board leaves
        # them out (nothing left to bid), which otherwise looks like "my quotes did not arrive".
        'hidden_submitted': sum(1 for r in rows if r['status'] == 'SUBMITTED'),
    })


@login_required
@require_GET
def compare_quotes(request, sol_number):
    """XHR fragment: every quote per line, side by side (the "Vehicle Comparison")."""
    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)
    lines = []
    for line in solicitation.lines.order_by('line_number', 'pk'):
        quotes = sorted(
            QuoteSupplierQuote.objects.filter(line=line)
            .select_related('supplier', 'packaging_vendor', 'source_email'),
            key=lambda q: (q.landed_unit_cost, q.pk),
        )
        if not quotes:
            continue
        best_landed = quotes[0].landed_unit_cost
        best_days = min(q.lead_time_days for q in quotes)
        for q in quotes:
            q.over_days = bool(line.delivery_days and q.lead_time_days > line.delivery_days)
            q.is_cheapest = q.landed_unit_cost == best_landed
            q.is_fastest = q.lead_time_days == best_days
            q.landed_delta = q.landed_unit_cost - best_landed
        lines.append({'line': line, 'quotes': quotes})
    bid_locked = QuoteBid.objects.filter(
        line__solicitation=solicitation, bid_status=QuoteBid.STATUS_SUBMITTED,
    ).exists()
    return render(request, 'quote/bids/_compare.html', {
        'solicitation': solicitation, 'lines': lines, 'bid_locked': bid_locked,
    })


@login_required
@require_POST
def select_quote(request, quote_id):
    """POST -- "Select this bid": a rep's pick overrides the automatic lowest."""
    quote = get_object_or_404(QuoteSupplierQuote.objects.select_related('line'), pk=quote_id)
    if QuoteBid.objects.filter(line_id=quote.line_id, bid_status=QuoteBid.STATUS_SUBMITTED).exists():
        return JsonResponse({'ok': False, 'error': 'That line was already submitted.'}, status=400)
    bid_service.select_quote(quote)
    return JsonResponse({'ok': True})


# ── Bid builder ──────────────────────────────────────────────────────────────

class _FormError(ValueError):
    pass


def _text(request, name, upper=False, max_len=None):
    value = (request.POST.get(name) or '').strip()
    if upper:
        value = value.upper()
    return value[:max_len] if max_len else value


def _int(request, name, label):
    raw = (request.POST.get(name) or '').strip()
    if not raw.isdigit():
        raise _FormError(f'{label} must be a whole number.')
    return int(raw)


def _parse_form(request, lines):
    header = {
        'quoter_cage': _text(request, 'h_quoter_cage', upper=True, max_len=5),
        'quote_for_cage': _text(request, 'h_quote_for_cage', upper=True, max_len=5),
        'bid_type_code': _text(request, 'h_bid_type_code', upper=True, max_len=2),
        'payment_terms': _text(request, 'h_payment_terms', max_len=2),
        'vendor_quote_number': _text(request, 'h_vendor_quote_number', max_len=15),
        'days_quote_valid': _int(request, 'h_days_quote_valid', 'Days quote valid'),
        'meets_packaging_requirement': _text(request, 'h_meets_packaging_requirement', upper=True, max_len=1),
        'fob_point': _text(request, 'h_fob_point', upper=True, max_len=1),
        'inspection_point': _text(request, 'h_inspection_point', upper=True, max_len=1),
        'bid_remarks': _text(request, 'h_bid_remarks', max_len=255),
    }
    lines_data = {}
    for line in lines:
        p = f'l{line.pk}_'
        if f'{p}unit_price' not in request.POST:
            continue
        try:
            price = cost.to_decimal(request.POST.get(f'{p}unit_price'), 'Unit price', allow_blank=False)
        except cost.CostError as exc:
            raise _FormError(f'Line {line.line_number}: {exc}') from exc
        lines_data[line.pk] = {
            'unit_price': price,
            'delivery_days': _int(request, f'{p}delivery_days', f'Line {line.line_number} delivery days'),
            'first_article_waiver': _text(request, f'{p}first_article_waiver', upper=True, max_len=1),
            'hazardous_material': _text(request, f'{p}hazardous_material', upper=True, max_len=1) or 'N',
            'material_requirements': _text(request, f'{p}material_requirements', max_len=1) or '0',
            'manufacturer_dealer': _text(request, f'{p}manufacturer_dealer', upper=True, max_len=2),
            'mfg_source_cage': _text(request, f'{p}mfg_source_cage', upper=True, max_len=5),
            'part_number_offered_code': _text(request, f'{p}part_number_offered_code', max_len=1),
            'part_number_offered_cage': _text(request, f'{p}part_number_offered_cage', upper=True, max_len=5),
            'part_number_offered': _text(request, f'{p}part_number_offered', max_len=40),
            'higher_level_quality_code': _text(request, f'{p}higher_level_quality_code', upper=True, max_len=1),
        }
    return header, lines_data


@login_required
def bid_builder(request, sol_number):
    """GET/POST /quote/bids/<sol>/ -- stage one bid per line from the selected quotes."""
    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)
    lines = list(solicitation.lines.order_by('line_number', 'pk'))

    checks_by_line = {}
    if request.method == 'POST':
        try:
            header, lines_data = _parse_form(request, lines)
        except _FormError as exc:
            messages.error(request, str(exc))
            return redirect(reverse('quote:bid_builder', args=[sol_number]))
        results = bid_service.save_bids(
            solicitation, header, lines_data, request.user,
            mark_ready=request.POST.get('action') == 'ready',
        )
        errors = sum(1 for _, checks in results if bid_service.has_errors(checks))
        if request.POST.get('action') == 'ready' and not errors:
            messages.success(request, f'{sol_number} is ready to export.')
            return redirect(f"{reverse('quote:bid_board')}?tab=ready")
        if errors:
            messages.error(request, f'{errors} line(s) have problems to fix before export.')
        else:
            messages.success(request, 'Draft saved.')
        checks_by_line = {bid.line_id: checks for bid, checks in results}

    entries = []
    for line in lines:
        bid = bid_service.bid_for(line, request.user)
        quote = bid.selected_quote
        entries.append({
            'line': line,
            'bid': bid,
            'quote': quote,
            'quote_count': QuoteSupplierQuote.objects.filter(line=line).count(),
            'checks': checks_by_line.get(line.pk) if line.pk in checks_by_line
            else (bid_service.preflight(bid) if bid.pk else []),
            'item_indicator': bid_service._template_cell(line, bid_service.COL_ITEM_DESCRIPTION),
            'locked': bid.bid_status == QuoteBid.STATUS_SUBMITTED,
        })
    header_bid = next((e['bid'] for e in entries if e['quote'] or e['bid'].pk), entries[0]['bid'] if entries else None)
    return render(request, 'quote/bids/builder.html', {
        'section': 'bids',
        'solicitation': solicitation,
        'entries': entries,
        'header': header_bid,
        'auto_award': bid_service.is_auto_award(sol_number),
        'bid_types': QuoteBid.BID_TYPE_CHOICES,
        'part_codes': bid_service.PART_OFFERED_CODES.items(),
        'cages': bid_service.CompanyCAGE.objects.filter(is_active=True).order_by('-is_default', 'cage_code'),
        'all_locked': entries and all(e['locked'] for e in entries),
    })


# ── Export ───────────────────────────────────────────────────────────────────

@login_required
def bid_export(request):
    """GET: READY bids with pre-flight. POST ids -> download the BQ file."""
    if request.method == 'POST':
        ids = [int(i) for i in request.POST.getlist('bid_ids') if i.isdigit()]
        try:
            filename, content = bid_service.export_bids(ids, request.user)
        except bid_service.BidExportError as exc:
            for sol, problem in exc.problems[:15]:
                messages.error(request, f'{sol}: {problem}' if sol else problem)
            return redirect('quote:bid_export')
        response = HttpResponse(content, content_type='text/plain; charset=iso-8859-1')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        messages.success(
            request,
            f'{filename} downloaded ({len(ids)} line(s)). Upload it to DIBBS; '
            'if DIBBS rejects it, reopen the bids from Bid Board > Submitted.',
        )
        return response

    ready = list(
        QuoteBid.objects.filter(bid_status=QuoteBid.STATUS_READY)
        .select_related('line__solicitation', 'selected_quote__supplier')
        .order_by('line__solicitation__return_by_date', 'line__solicitation__solicitation_number',
                  'line__line_number')
    )
    for bid in ready:
        bid.checks = bid_service.preflight(bid)
        bid.blocked = bid_service.has_errors(bid.checks)
    return render(request, 'quote/bids/export.html', {
        'section': 'bids',
        'export_page': True,
        'bids': ready,
        'exportable': sum(1 for b in ready if not b.blocked),
    })


@login_required
@require_GET
def bid_reexport(request, filename):
    try:
        content = bid_service.reexport(filename)
    except bid_service.BidExportError:
        messages.error(request, 'That export file is not on record.')
        return redirect(f"{reverse('quote:bid_board')}?tab=submitted")
    response = HttpResponse(content, content_type='text/plain; charset=iso-8859-1')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_POST
def bid_reopen_export(request, filename):
    """POST -- DIBBS rejected an upload: put every bid in that file back to READY."""
    bids = QuoteBid.objects.filter(exported_bq_file=filename).select_related('line')
    reopened = sum(1 for bid in bids if bid_service.reopen_bid(bid))
    messages.info(request, f'{reopened} bid(s) from {filename} are back in Ready.')
    return redirect(f"{reverse('quote:bid_board')}?tab=ready")
