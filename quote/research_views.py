"""Supplier Research page shell, panel fragments, and Excel export."""
import logging
import time
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from quote.forms import CageLookupForm
from quote.services import supplier_research as sr

logger = logging.getLogger(__name__)

# (key, card title) in on-page order.
PANELS = (
    ('status', 'STATZ Status'),
    ('sam', 'SAM.gov Entity'),
    ('awards', 'Award History'),
    ('approved', 'Approved Sources'),
)
PANEL_KEYS = {key for key, _title in PANELS}
COLLAPSE_AFTER = 25  # table rows visible before the "Show all" toggle


@login_required
@require_GET
def supplier_research(request):
    """Shell only: validates the CAGE and renders four empty panel cards.

    No data queries here -- every panel loads from supplier_research_panel.
    """
    cage_raw = (request.GET.get('cage') or '').strip()
    form = CageLookupForm(data={'cage': cage_raw}) if cage_raw else CageLookupForm()
    context = {'section': 'supplier_research', 'form': form, 'cage': None, 'panels': []}
    if cage_raw and form.is_valid():
        cage = form.cleaned_data['cage']
        context['cage'] = cage
        context['panels'] = [
            (key, title, reverse('quote:supplier_research_panel', args=[cage, key]))
            for key, title in PANELS
        ]
    return render(request, 'quote/supplier_research.html', context)


def _panel_context(request, cage, panel):
    if panel == 'status':
        return {'existing_supplier': sr.find_existing_supplier(cage)}
    if panel == 'sam':
        # refresh=1 is honored on the SAM panel only.
        force = request.GET.get('refresh') == '1'
        return {
            'sam': sr.get_sam_entity(cage, force_refresh=force),
            'refresh_url': reverse('quote:supplier_research_panel', args=[cage, 'sam']) + '?refresh=1',
        }
    if panel == 'awards':
        summary = sr.get_award_summary(cage)
        awards = sr.get_awards(cage, limit=sr.AWARD_DISPLAY_LIMIT)
        return {
            'award_summary': summary,
            'awards': awards,
            'awards_truncated': summary['total_awards'] > sr.AWARD_DISPLAY_LIMIT,
            'collapse_after': COLLAPSE_AFTER,
        }
    approved = sr.get_approved_sources(cage)
    return {
        'approved_sources': approved['rows'],
        'has_company_name': approved['has_company_name'],
        'collapse_after': COLLAPSE_AFTER,
    }


@login_required
@require_GET
def supplier_research_panel(request, cage, panel):
    form = CageLookupForm(data={'cage': cage})
    if not form.is_valid():
        return HttpResponseBadRequest('Invalid CAGE code.')
    if panel not in PANEL_KEYS:
        raise Http404('Unknown panel.')
    cage_norm = form.cleaned_data['cage']
    started = time.monotonic()
    context = _panel_context(request, cage_norm, panel)
    context['cage'] = cage_norm
    response = render(request, f'quote/research/_panel_{panel}.html', context)
    logger.info(
        'supplier_research panel=%s cage=%s ms=%d',
        panel, cage_norm, (time.monotonic() - started) * 1000,
    )
    return response


@login_required
@require_GET
def supplier_research_export(request, cage):
    form = CageLookupForm(data={'cage': cage})
    if not form.is_valid():
        return HttpResponseBadRequest('Invalid CAGE code.')
    cage_norm = form.cleaned_data['cage']
    wb = sr.build_research_workbook(cage_norm)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    stamp = timezone.localdate().strftime('%Y%m%d')
    filename = f'Supplier_Research_{cage_norm}_{stamp}.xlsx'
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
