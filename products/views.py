"""
NSN Portal views — read-focused surfaces with one bounded logistics write path.

Cross-app model imports are lazy inside methods only (never at module level).
"""
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView, TemplateView

from products.forms import NsnLogisticsForm
from products.models import Nsn
from products.nsn_utils import (
    fsc_of,
    format_nsn,
    is_plausible_nsn,
    niin_of,
    normalize_nsn,
    nsn_populated_score,
    nsn_query_variants,
)

_OBSERVATORY_STATS_CACHE_KEY = 'products:observatory_stats'
_OBSERVATORY_STATS_TTL = 600

_ALNUM_13_RE = re.compile(r'^[A-Za-z0-9]{13}$')
_DIGITS_9_RE = re.compile(r'^\d{9}$')
_ALNUM_5_RE = re.compile(r'^[A-Za-z0-9]{5}$')


def _duplicate_count_for(nsn):
    normalized = nsn.nsn_normalized or normalize_nsn(nsn.nsn_code or '')
    if not normalized:
        return 0
    return Nsn.objects.filter(nsn_normalized=normalized).count()


def _resolve_canonical_nsn_queryset(normalized):
    """Return queryset ordered canonical-first for a normalized code."""
    if not normalized:
        return Nsn.objects.none()
    rows = list(Nsn.objects.filter(nsn_normalized=normalized))
    if not rows:
        return Nsn.objects.none()
    rows.sort(key=lambda n: (-nsn_populated_score(n), n.pk))
    return Nsn.objects.filter(pk=rows[0].pk)


def _batched_suppliers_by_cage(cage_codes):
    from suppliers.models import Supplier

    cage_set = {c for c in cage_codes if c}
    if not cage_set:
        return {}
    return {
        s.cage_code: s
        for s in Supplier.objects.filter(cage_code__in=cage_set)
    }


def _batched_sam_names_by_cage(cage_codes):
    from sales.models.sam_cache import SAMEntityCache

    cage_set = {c for c in cage_codes if c}
    if not cage_set:
        return {}
    return {
        row.cage_code: row.entity_name
        for row in SAMEntityCache.objects.filter(cage_code__in=cage_set)
        if row.entity_name
    }


def _cage_search_token(raw: str) -> str:
    """Return a normalized 5-character CAGE token, or empty if input is not CAGE-shaped."""
    token = normalize_nsn(raw)
    if _ALNUM_5_RE.match(token):
        return token
    return ''


def _suppliers_matching_cage(cage):
    from suppliers.models import Supplier

    cage_u = (cage or '').strip().upper()
    if not cage_u:
        return []
    exact = list(Supplier.objects.filter(cage_code__iexact=cage_u)[:50])
    if exact:
        return exact
    # Fallback for whitespace-padded cage_code values without wrapping indexed columns.
    prefix = cage_u[:3]
    for supplier in Supplier.objects.exclude(cage_code__isnull=True).exclude(cage_code='').filter(
        cage_code__istartswith=prefix,
    )[:200]:
        if (supplier.cage_code or '').strip().upper() == cage_u:
            exact.append(supplier)
            if len(exact) >= 50:
                break
    return exact


def _active_no_quote_cages(cage_codes):
    from sales.models.no_quote import NoQuoteCAGE

    cage_set = {c for c in cage_codes if c}
    if not cage_set:
        return set()
    return set(
        NoQuoteCAGE.objects.filter(cage_code__in=cage_set, is_active=True)
        .values_list('cage_code', flat=True)
    )


def _nsn_pk_for_code(nsn_code):
    normalized = normalize_nsn(nsn_code or '')
    if not normalized:
        return None
    rows = list(Nsn.objects.filter(nsn_normalized=normalized))
    if not rows:
        return None
    rows.sort(key=lambda n: (-nsn_populated_score(n), n.pk))
    return rows[0].pk


class ObservatoryView(LoginRequiredMixin, TemplateView):
    template_name = 'products/observatory.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['stats'] = self._get_stats()
        context['recent_awards'] = self._get_recent_awards()
        context['recent_nsns'] = self._get_recent_nsns()
        return context

    def _get_recent_nsns(self):
        from django.utils import timezone

        now = timezone.now()
        candidates = list(
            Nsn.objects.exclude(nsn_code__isnull=True)
            .exclude(nsn_code='')
            .filter(modified_on__lte=now)
            .order_by('-modified_on')[:40]
        )
        recent = []
        for nsn in candidates:
            if not is_plausible_nsn(nsn.nsn_code):
                continue
            recent.append(nsn)
            if len(recent) >= 10:
                break
        return recent

    def _get_stats(self):
        cached = cache.get(_OBSERVATORY_STATS_CACHE_KEY)
        if cached is not None:
            return cached

        from sales.models.solicitations import NsnProcurementHistory
        from sales.models.approved_sources import ApprovedSource
        from sales.models.awards import DibbsAward, WeWonAward

        total_nsns = Nsn.objects.count()
        catalog_normalized = set(
            Nsn.objects.exclude(nsn_normalized='').values_list('nsn_normalized', flat=True)
        )
        procurement_nsns = set(
            NsnProcurementHistory.objects.values_list('nsn', flat=True).distinct()
        )
        nsns_with_history = len(catalog_normalized & procurement_nsns)
        # Plain unfiltered table count — verified 2026-07-07; gap vs physical rows is data drift.
        total_procurement_records = NsnProcurementHistory.objects.count()
        awards_won = DibbsAward.objects.filter(
            id__in=WeWonAward.objects.values('id'),
            is_faux=False,
        ).count()
        active_approved_cages = (
            ApprovedSource.objects.exclude(approved_cage='')
            .values('approved_cage')
            .distinct()
            .count()
        )

        stats = {
            'total_nsns': total_nsns,
            'nsns_with_history': nsns_with_history,
            'total_procurement_records': total_procurement_records,
            'awards_won': awards_won,
            'active_approved_cages': active_approved_cages,
        }
        cache.set(_OBSERVATORY_STATS_CACHE_KEY, stats, _OBSERVATORY_STATS_TTL)
        return stats

    def _get_recent_awards(self):
        from sales.models.awards import DibbsAward

        # Bounded prefetch + in-memory dedup — full-table Window() on MSSQL scanned
        # ~465K partition winners (~30s). Candidates are already date-ordered.
        _CANDIDATE_LIMIT = 400
        candidates = (
            DibbsAward.objects.exclude(nsn__isnull=True)
            .exclude(nsn='')
            .order_by(
                F('aw_file_date').desc(nulls_last=True),
                F('posted_date').desc(nulls_last=True),
                '-id',
            )[:_CANDIDATE_LIMIT]
        )
        seen = set()
        awards = []
        for award in candidates:
            key = (award.award_basic_number or '', award.delivery_order_number or '')
            if key in seen:
                continue
            seen.add(key)
            awards.append(award)
            if len(awards) >= 10:
                break

        for award in awards:
            award.nsn_dossier_pk = _nsn_pk_for_code(award.nsn)
        return awards


@login_required
@require_http_methods(['GET'])
def portal_search(request):
    raw_q = (request.GET.get('q') or '').strip()
    if not raw_q:
        return redirect('products:observatory')

    cleaned = normalize_nsn(raw_q)
    raw_stripped = raw_q.strip()

    if _ALNUM_13_RE.match(cleaned):
        return _search_nsn_full(request, cleaned, raw_stripped)

    if _DIGITS_9_RE.match(cleaned):
        return _search_niin(request, cleaned)

    cage_token = _cage_search_token(raw_stripped)
    if cage_token:
        return _search_cage(request, cage_token)

    return _search_text(request, raw_stripped)


def _search_nsn_full(request, normalized, raw_stripped):
    matches = list(Nsn.objects.filter(nsn_normalized=normalized))
    if len(matches) == 1:
        return redirect('products:nsn_detail', pk=matches[0].pk)
    if len(matches) > 1:
        matches.sort(key=lambda n: (-nsn_populated_score(n), n.pk))
        return render(request, 'products/search_results.html', {
            'query': raw_stripped,
            'nsn_hits': matches[:50],
            'supplier_hits': [],
            'part_hits': [],
        })
    return render(request, 'products/search_results.html', {
        'query': raw_stripped,
        'nsn_hits': [],
        'supplier_hits': [],
        'part_hits': [],
        'not_in_catalog': format_nsn(normalized) or normalized,
    })


def _search_niin(request, niin):
    from sales.models.solicitations import SolicitationLine

    nsn_hits = list(
        Nsn.objects.filter(nsn_normalized__endswith=niin)
        .order_by('nsn_code')[:50]
    )
    line_nsns = list(
        SolicitationLine.objects.filter(niin=niin)
        .values_list('nsn', flat=True)
        .distinct()[:50]
    )
    seen_pks = {n.pk for n in nsn_hits}
    for code in line_nsns:
        pk = _nsn_pk_for_code(code)
        if pk and pk not in seen_pks:
            nsn_hits.append(Nsn.objects.get(pk=pk))
            seen_pks.add(pk)
        if len(nsn_hits) >= 50:
            break

    return render(request, 'products/search_results.html', {
        'query': niin,
        'nsn_hits': nsn_hits[:50],
        'supplier_hits': [],
        'part_hits': [],
    })


def _search_cage(request, cage):
    from sales.models.sam_cache import SAMEntityCache

    cage = (cage or '').strip().upper()
    suppliers = _suppliers_matching_cage(cage)
    if len(suppliers) == 1:
        return redirect('products:supplier_nsns', pk=suppliers[0].pk)

    if not suppliers:
        sam = SAMEntityCache.objects.filter(cage_code__iexact=cage).first()
        if sam:
            return render(request, 'products/search_results.html', {
                'query': cage,
                'nsn_hits': [],
                'supplier_hits': [],
                'part_hits': [],
                'sam_only': sam,
            })

    return render(request, 'products/search_results.html', {
        'query': cage,
        'nsn_hits': [],
        'supplier_hits': suppliers[:50],
        'part_hits': [],
    })


def _search_text(request, query):
    from sales.models.approved_sources import ApprovedSource
    from sales.models.quotes import SupplierQuote

    part_hits = []
    seen_pks = set()

    def _add_nsn_from_code(code, part_number='', source=''):
        pk = _nsn_pk_for_code(code)
        if pk and pk not in seen_pks:
            seen_pks.add(pk)
            part_hits.append({
                'nsn': Nsn.objects.get(pk=pk),
                'part_number': part_number,
                'source': source,
            })

    for row in ApprovedSource.objects.filter(part_number__iexact=query)[:50]:
        _add_nsn_from_code(row.nsn, row.part_number, 'Approved Source')
    if len(part_hits) < 50:
        for row in ApprovedSource.objects.filter(part_number__icontains=query)[:50]:
            _add_nsn_from_code(row.nsn, row.part_number, 'Approved Source')
            if len(part_hits) >= 50:
                break

    if len(part_hits) < 50:
        for row in SupplierQuote.objects.filter(part_number_offered__icontains=query)[:50]:
            _add_nsn_from_code(row.nsn, row.part_number_offered, 'Supplier Quote')
            if len(part_hits) >= 50:
                break

    nsn_hits = list(
        Nsn.objects.filter(
            Q(part_number__icontains=query) | Q(description__icontains=query)
        ).order_by('nsn_code')[:50]
    )

    return render(request, 'products/search_results.html', {
        'query': query,
        'nsn_hits': nsn_hits,
        'supplier_hits': [],
        'part_hits': part_hits[:50],
    })


class NsnDetailView(LoginRequiredMixin, DetailView):
    model = Nsn
    template_name = 'products/nsn_detail.html'
    context_object_name = 'nsn'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        nsn = self.object
        variants = nsn_query_variants(nsn.nsn_code or nsn.nsn_normalized or '')
        dup_count = _duplicate_count_for(nsn)

        context.update({
            'formatted_nsn': format_nsn(nsn.nsn_normalized or nsn.nsn_code or ''),
            'fsc': fsc_of(nsn.nsn_normalized),
            'niin': niin_of(nsn.nsn_normalized),
            'duplicate_count': dup_count,
            'duplicate_admin_url': (
                reverse('admin:products_nsn_changelist')
                + f'?nsn_normalized__exact={nsn.nsn_normalized}'
                if dup_count > 1 and nsn.nsn_normalized else ''
            ),
            'logistics_form': NsnLogisticsForm(instance=nsn),
            'price_series': self._get_price_series(variants),
            'procurement_history': self._get_procurement_history(variants),
            'procurement_history_all': self.request.GET.get('history') == 'all',
            'approved_sources': self._get_approved_sources_data(variants),
            'our_activity': self._get_our_activity(variants),
            'contracts_panel': self._get_contracts_panel(nsn, variants),
            'demand_history': self._get_demand_history(variants),
            'demand_history_all': self.request.GET.get('demand') == 'all',
        })
        return context

    def _get_price_series(self, variants):
        if not variants:
            return {}

        from sales.models.solicitations import NsnProcurementHistory
        from sales.models.quotes import SupplierQuote
        from sales.models.bids import GovernmentBid
        from sales.models.awards import DibbsAward

        series = {}

        gov_rows = (
            NsnProcurementHistory.objects.filter(nsn__in=variants)
            .order_by('award_date')
        )
        if gov_rows.exists():
            series['govt_paid'] = [
                {
                    'x': row.award_date.isoformat(),
                    'y': float(row.unit_cost),
                }
                for row in gov_rows
            ]

        quote_rows = (
            SupplierQuote.objects.filter(nsn__in=variants)
            .select_related('supplier')
            .order_by('quote_date')
        )
        if quote_rows.exists():
            series['supplier_quoted'] = [
                {
                    'x': row.quote_date.date().isoformat(),
                    'y': float(row.unit_price),
                    'supplier': row.supplier.name if row.supplier_id else '',
                }
                for row in quote_rows
            ]

        bid_rows = (
            GovernmentBid.objects.filter(
                line__nsn__in=variants,
                bid_status__in=['SUBMITTED', 'ACCEPTED'],
            )
            .select_related('line')
            .order_by('submitted_at')
        )
        if bid_rows.exists():
            series['we_bid'] = [
                {
                    'x': row.submitted_at.date().isoformat() if row.submitted_at else '',
                    'y': float(row.unit_price),
                }
                for row in bid_rows
                if row.submitted_at
            ]

        award_rows = (
            DibbsAward.objects.filter(nsn__in=variants, is_faux=False)
            .order_by('award_date')
        )
        if award_rows.exists():
            series['awards'] = [
                {
                    'x': row.award_date.isoformat(),
                    'awardee_cage': row.awardee_cage or '',
                    'total_price': float(row.total_contract_price) if row.total_contract_price else None,
                    'we_won': row.we_won,
                }
                for row in award_rows
            ]

        return series

    def _get_procurement_history(self, variants):
        from sales.models.solicitations import NsnProcurementHistory

        if not variants:
            return []

        qs = (
            NsnProcurementHistory.objects.filter(nsn__in=variants)
            .order_by('-award_date')
        )
        if self.request.GET.get('history') != 'all':
            qs = qs[:25]

        rows = list(qs)
        cages = {r.cage_code for r in rows if r.cage_code}
        suppliers = _batched_suppliers_by_cage(cages)
        sam_names = _batched_sam_names_by_cage(cages)

        result = []
        for row in rows:
            cage = row.cage_code or ''
            supplier = suppliers.get(cage)
            if supplier and supplier.name:
                cage_name = supplier.name
            elif sam_names.get(cage):
                cage_name = sam_names[cage]
            else:
                cage_name = ''
            result.append({
                'row': row,
                'cage_name': cage_name,
            })
        return result

    def _get_approved_sources_data(self, variants):
        from sales.models.approved_sources import ApprovedSource

        empty = {'rows': [], 'total_count': 0, 'resolved_count': 0, 'orphaned_count': 0}
        if not variants:
            return empty

        base_qs = ApprovedSource.objects.filter(nsn__in=variants)
        orphaned_count = base_qs.filter(import_batch__isnull=True).count()

        distinct_rows = list(
            base_qs.filter(import_batch__isnull=False)
            .values('approved_cage', 'part_number', 'company_name', 'nsn')
            .distinct()
        )
        seen = set()
        deduped = []
        for r in distinct_rows:
            key = (r.get('approved_cage') or '', r.get('part_number') or '')
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)

        if not deduped:
            return {'rows': [], 'total_count': 0, 'resolved_count': 0, 'orphaned_count': orphaned_count}

        cage_set = {r['approved_cage'] for r in deduped if r.get('approved_cage')}
        suppliers_by_cage = _batched_suppliers_by_cage(cage_set)
        sam_names = _batched_sam_names_by_cage(cage_set)
        no_quote = _active_no_quote_cages(cage_set)

        rows = []
        for r in deduped:
            cage = r.get('approved_cage') or ''
            supplier = suppliers_by_cage.get(cage)
            is_resolved = supplier is not None
            if is_resolved and supplier.name:
                company_name = supplier.name
            elif sam_names.get(cage):
                company_name = sam_names[cage]
            elif r.get('company_name'):
                company_name = r['company_name']
            else:
                company_name = 'Unknown supplier'
            rows.append({
                'cage_code': cage,
                'company_name': company_name,
                'part_number': r.get('part_number') or '',
                'supplier': supplier,
                'supplier_pk': supplier.pk if supplier else None,
                'is_resolved': is_resolved,
                'no_quote': cage in no_quote,
            })

        rows.sort(key=lambda r: (not r['is_resolved'], (r['company_name'] or '').lower()))

        return {
            'rows': rows,
            'total_count': len(rows),
            'resolved_count': sum(1 for r in rows if r['is_resolved']),
            'orphaned_count': orphaned_count,
        }

    def _get_our_activity(self, variants):
        from sales.models.quotes import SupplierQuote
        from sales.models.awards import DibbsAward, DibbsAwardMod

        quotes = list(
            SupplierQuote.objects.filter(nsn__in=variants)
            .select_related('supplier')
            .order_by('-quote_date')[:50]
        ) if variants else []

        awards = list(
            DibbsAward.objects.filter(nsn__in=variants, is_faux=False)
            .order_by('-award_date')[:50]
        ) if variants else []

        award_ids = [a.pk for a in awards]
        mod_counts = {}
        matched_contracts = {}
        if award_ids:
            for row in (
                DibbsAwardMod.objects.filter(award_id__in=award_ids)
                .values('award_id')
                .annotate(mod_count=Count('id'))
                .order_by()  # clear Meta ordering — MSSQL rejects ORDER BY mod_date with GROUP BY award_id
            ):
                mod_counts[row['award_id']] = row['mod_count']
            for mod in (
                DibbsAwardMod.objects.filter(award_id__in=award_ids)
                .exclude(matched_contract__isnull=True)
                .select_related('matched_contract')
                .order_by('-mod_date')[:50]
            ):
                if mod.award_id not in matched_contracts:
                    matched_contracts[mod.award_id] = mod.matched_contract

        award_rows = []
        for award in awards:
            award_rows.append({
                'award': award,
                'mod_count': mod_counts.get(award.pk, 0),
                'matched_contract': matched_contracts.get(award.pk),
            })

        return {'quotes': quotes, 'awards': award_rows}

    def _get_contracts_panel(self, nsn, variants):
        from contracts.models import Clin, IdiqContractDetails

        clins = list(
            Clin.objects.filter(nsn=nsn)
            .select_related('contract', 'contract__status')
            .order_by('-contract__award_date')[:50]
        )
        idiq_details = list(
            IdiqContractDetails.objects.filter(nsn=nsn)
            .select_related('idiq_contract', 'supplier')
            .order_by('-idiq_contract__award_date')[:50]
        )

        mod_contracts = []
        if variants:
            from sales.models.awards import DibbsAwardMod
            seen_contract_pks = set()
            for mod in (
                DibbsAwardMod.objects.filter(nsn__in=variants)
                .exclude(matched_contract__isnull=True)
                .select_related('matched_contract', 'matched_contract__status')
                .order_by('-mod_date')[:25]
            ):
                if mod.matched_contract_id not in seen_contract_pks:
                    seen_contract_pks.add(mod.matched_contract_id)
                    mod_contracts.append(mod)

        return {
            'clins': clins,
            'idiq_details': idiq_details,
            'mod_contracts': mod_contracts,
        }

    def _get_demand_history(self, variants):
        from sales.models.solicitations import SolicitationLine

        if not variants:
            return []

        qs = (
            SolicitationLine.objects.filter(nsn__in=variants)
            .select_related('solicitation')
            .order_by('-solicitation__return_by_date', '-id')
        )
        if self.request.GET.get('demand') != 'all':
            qs = qs[:25]
        return list(qs)


@login_required
@require_http_methods(['POST'])
def nsn_logistics_update(request, pk):
    nsn = get_object_or_404(Nsn, pk=pk)
    form = NsnLogisticsForm(request.POST, instance=nsn)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.modified_by = request.user
        obj.save()
        messages.success(request, 'Logistics data saved.')
        return redirect('products:nsn_detail', pk=pk)
    messages.error(request, 'Could not save logistics data. Please check the form.')
    return redirect('products:nsn_detail', pk=pk)


class SupplierNsnView(LoginRequiredMixin, DetailView):
    template_name = 'products/supplier_nsns.html'
    context_object_name = 'supplier'

    def get_queryset(self):
        from suppliers.models import Supplier
        return Supplier.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supplier = self.object
        cage = (supplier.cage_code or '').strip()

        from sales.models.approved_sources import ApprovedSource
        from sales.models.quotes import SupplierQuote
        from sales.models.awards import DibbsAward
        from sales.models.suppliers import SupplierNSN
        from sales.models.no_quote import NoQuoteCAGE

        no_quote = False
        if cage:
            no_quote = NoQuoteCAGE.objects.filter(cage_code=cage, is_active=True).exists()

        context['no_quote'] = no_quote
        context['has_cage'] = bool(cage)

        approved_rows = []
        if cage:
            raw = list(
                ApprovedSource.objects.filter(approved_cage=cage)
                .values('nsn', 'part_number')
                .distinct()
            )
            seen = set()
            for r in raw:
                key = (r['nsn'], r.get('part_number') or '')
                if key in seen:
                    continue
                seen.add(key)
                pk = _nsn_pk_for_code(r['nsn'])
                approved_rows.append({
                    'nsn_code': r['nsn'],
                    'part_number': r.get('part_number') or '',
                    'dossier_pk': pk,
                })
            context['approved_page'] = self._paginate(approved_rows, 'approved_page')

        quote_qs = SupplierQuote.objects.filter(supplier=supplier).order_by('-quote_date')
        context['quotes_page'] = self._paginate_queryset(quote_qs, 'quotes_page')

        won_rows = []
        if cage:
            won_qs = (
                DibbsAward.objects.filter(awardee_cage=cage, is_faux=False)
                .order_by('-award_date')
            )
            context['won_page'] = self._paginate_queryset(won_qs, 'won_page')
        else:
            context['won_page'] = None

        manual_qs = SupplierNSN.objects.filter(supplier=supplier).order_by('-added_at')
        context['manual_page'] = self._paginate_queryset(manual_qs, 'manual_page')

        return context

    def _paginate(self, items, param):
        paginator = Paginator(items, 100)
        page_num = self.request.GET.get(param, 1)
        return paginator.get_page(page_num)

    def _paginate_queryset(self, qs, param):
        paginator = Paginator(qs, 100)
        page_num = self.request.GET.get(param, 1)
        page = paginator.get_page(page_num)
        if hasattr(qs.model, 'nsn'):
            for obj in page.object_list:
                obj.dossier_pk = _nsn_pk_for_code(getattr(obj, 'nsn', ''))
        return page
