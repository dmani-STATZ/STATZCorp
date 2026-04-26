import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import DetailView

from STATZWeb.decorators import conditional_login_required
from products.models import Nsn


_DECIMAL_FIELDS = ('unit_weight', 'unit_length', 'unit_width', 'unit_height')


@method_decorator(conditional_login_required, name='dispatch')
class NsnDetailView(DetailView):
    model = Nsn
    template_name = 'products/nsn_detail.html'
    context_object_name = 'nsn'

    def get_context_data(self, **kwargs):
        from contracts.models import Clin, IdiqContractDetails

        context = super().get_context_data(**kwargs)
        nsn = self.object

        context['approved_sources'] = self.get_approved_sources_data()
        context['referencing_clins'] = (
            Clin.objects
            .filter(nsn=nsn)
            .select_related('contract')[:50]
        )
        context['referencing_idiq_details'] = (
            IdiqContractDetails.objects
            .filter(nsn=nsn)
            .select_related('idiq_contract', 'supplier')[:50]
        )
        context['has_packout_data'] = nsn.unit_weight is not None
        return context

    def get_approved_sources_data(self):
        """
        Build the approved-sources panel data for this NSN.

        Joins `sales.ApprovedSource` (string-keyed by `nsn` and `approved_cage`)
        to `Nsn.nsn_code` and `Supplier.cage_code`. Neither side is an FK; both
        joins are pure string matches against externally imported data. CAGEs
        with no matching Supplier render as unresolved — that is normal, not an
        error.
        """
        from sales.models.approved_sources import ApprovedSource
        from suppliers.models import Supplier

        empty = {'rows': [], 'total_count': 0, 'resolved_count': 0, 'orphaned_count': 0}
        nsn_code = (self.object.nsn_code or '').strip()
        if not nsn_code:
            return empty

        base_qs = ApprovedSource.objects.filter(nsn=nsn_code)
        orphaned_count = base_qs.filter(import_batch__isnull=True).count()

        distinct_rows = list(
            base_qs
            .filter(import_batch__isnull=False)
            .values('approved_cage', 'part_number', 'company_name')
            .distinct()
        )
        if not distinct_rows:
            return {'rows': [], 'total_count': 0, 'resolved_count': 0, 'orphaned_count': orphaned_count}

        cage_set = {r['approved_cage'] for r in distinct_rows if r.get('approved_cage')}
        suppliers_by_cage = {
            s.cage_code: s
            for s in Supplier.objects.filter(cage_code__in=cage_set)
        }

        rows = []
        for r in distinct_rows:
            cage = r.get('approved_cage') or ''
            supplier = suppliers_by_cage.get(cage)
            is_resolved = supplier is not None
            if is_resolved and supplier.name:
                company_name = supplier.name
            elif r.get('company_name'):
                company_name = r['company_name']
            else:
                company_name = 'Unknown supplier'
            rows.append({
                'cage_code': cage,
                'company_name': company_name,
                'part_number': r.get('part_number'),
                'supplier': supplier,
                'is_resolved': is_resolved,
            })

        rows.sort(key=lambda r: (not r['is_resolved'], (r['company_name'] or '').lower()))

        return {
            'rows': rows,
            'total_count': len(rows),
            'resolved_count': sum(1 for r in rows if r['is_resolved']),
            'orphaned_count': orphaned_count,
        }


def _parse_decimal_field(raw, field_name):
    if raw is None:
        return None, None
    if isinstance(raw, str):
        s = raw.strip()
        if s == '':
            return None, None
    else:
        s = raw
    try:
        return Decimal(str(s)), None
    except (InvalidOperation, ValueError, TypeError):
        return None, f"{field_name} must be a number."


@login_required
@require_POST
def nsn_packout_update(request, pk):
    nsn = get_object_or_404(Nsn, pk=pk)

    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse(
            {'ok': False, 'errors': {'__all__': 'Invalid JSON body.'}},
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {'ok': False, 'errors': {'__all__': 'Body must be a JSON object.'}},
            status=400,
        )

    errors = {}
    updates = {}

    for field_name in _DECIMAL_FIELDS:
        if field_name not in payload:
            continue
        value, error = _parse_decimal_field(payload[field_name], field_name)
        if error:
            errors[field_name] = error
        else:
            updates[field_name] = value

    if 'packaging_notes' in payload:
        notes_raw = payload['packaging_notes']
        if notes_raw is None:
            updates['packaging_notes'] = ''
        elif isinstance(notes_raw, str):
            updates['packaging_notes'] = notes_raw
        else:
            errors['packaging_notes'] = 'packaging_notes must be a string.'

    if errors:
        return JsonResponse({'ok': False, 'errors': errors}, status=400)

    for k, v in updates.items():
        setattr(nsn, k, v)
    nsn.modified_by = request.user
    nsn.save()

    serialized = {}
    for k, v in updates.items():
        if isinstance(v, Decimal):
            serialized[k] = str(v)
        else:
            serialized[k] = v

    return JsonResponse({'ok': True, 'fields': serialized})
