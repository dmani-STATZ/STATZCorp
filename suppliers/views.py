import json

from django.db import models
from django.db.models import Q, Count, Sum, Case, When, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.utils import timezone
from django.views.generic import TemplateView, DetailView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404

from contracts.models import Contract, Clin
from suppliers.models import Supplier, SupplierDocument


class DashboardView(TemplateView):
    template_name = 'suppliers/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        suppliers_with_metrics = Supplier.objects.annotate(
            contract_count=Count('contract', distinct=True),
            contract_value=Coalesce(
                Sum('contract__contract_value'),
                0.0,
                output_field=models.FloatField(),
            ),
        )

        def is_manufacturer(qs):
            return qs.filter(
                Q(supplier_type__code__iexact='M')
                | Q(supplier_type__description__icontains='manufact')
            )

        def is_distributor(qs):
            return qs.filter(
                Q(supplier_type__code__iexact='D')
                | Q(supplier_type__description__icontains='distrib')
            )

        def is_packhouse(qs):
            return qs.filter(
                Q(is_packhouse=True)
                | Q(supplier_type__description__icontains='packhouse')
            )

        manufacturer_qs = is_manufacturer(suppliers_with_metrics)
        distributor_qs = is_distributor(suppliers_with_metrics)
        packhouse_qs = is_packhouse(suppliers_with_metrics)
        unspecified_qs = suppliers_with_metrics.filter(supplier_type__isnull=True, is_packhouse=False)
        other_qs = suppliers_with_metrics.exclude(pk__in=manufacturer_qs.values_list('pk', flat=True)) \
            .exclude(pk__in=distributor_qs.values_list('pk', flat=True)) \
            .exclude(pk__in=packhouse_qs.values_list('pk', flat=True)) \
            .exclude(pk__in=unspecified_qs.values_list('pk', flat=True))

        context['suppliers'] = suppliers_with_metrics.order_by('-created_on')[:10]
        context['top_suppliers_by_contract_count'] = suppliers_with_metrics.filter(
            contract_count__gt=0
        ).order_by('-contract_count', 'name')[:10]
        context['top_suppliers_by_contract_value'] = suppliers_with_metrics.filter(
            contract_value__gt=0
        ).order_by('-contract_value', 'name')[:10]
        context['top_manufacturers'] = manufacturer_qs.filter(contract_value__gt=0).order_by('-contract_value', 'name')[:5]
        context['top_distributors'] = distributor_qs.filter(contract_value__gt=0).order_by('-contract_value', 'name')[:5]

        context['type_counts'] = {
            'manufacturer': manufacturer_qs.count(),
            'distributor': distributor_qs.count(),
            'packhouse': packhouse_qs.count(),
            'other': other_qs.count(),
            'unspecified': unspecified_qs.count(),
        }

        contracts_qs = Contract.objects.filter(supplier__isnull=False)
        context['total_suppliers'] = Supplier.objects.count()
        context['total_contracts'] = contracts_qs.count()
        context['total_contract_value'] = contracts_qs.aggregate(
            total=Coalesce(
                Sum('contract_value'),
                0.0,
                output_field=models.FloatField(),
            )
        )['total'] or 0

        # Recently active suppliers based on contract activity
        recently_active = []
        seen = set()
        for contract in contracts_qs.order_by('-modified_on', '-created_on')[:50]:
            if contract.supplier_id and contract.supplier_id not in seen:
                recently_active.append({
                    'supplier': contract.supplier,
                    'last_activity': contract.modified_on,
                })
                seen.add(contract.supplier_id)
            if len(recently_active) >= 10:
                break
        context['recently_active_suppliers'] = recently_active
        return context


class SupplierDetailView(DetailView):
    model = Supplier
    template_name = 'suppliers/supplier_detail.html'
    context_object_name = 'supplier'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supplier = self.object
        context['contacts'] = supplier.contacts.all().order_by('name')
        context['documents'] = SupplierDocument.objects.filter(supplier=supplier).select_related('certification', 'classification')[:25]
        context['addresses'] = {
            'billing': supplier.billing_address,
            'shipping': supplier.shipping_address,
            'physical': supplier.physical_address,
        }
        context['compliance_flags'] = {
            'probation': supplier.probation,
            'conditional': supplier.conditional,
            'archived': supplier.archived,
        }
        context['contracts'] = Contract.objects.filter(supplier=supplier).select_related('status').annotate(
            performance_flag=Case(
                When(due_date_late=True, then=Value('Late')),
                default=Value(''),
                output_field=models.CharField(),
            )
        ).order_by('-award_date', '-created_on')

        context['clin_summary'] = Clin.objects.filter(supplier=supplier).aggregate(
            total_clins=Count('id'),
            total_value=Coalesce(Sum('quote_value'), 0.0, output_field=models.FloatField()),
        )
        return context


class SupplierEnrichView(LoginRequiredMixin, View):
    """
    GET: return enrichment suggestions as JSON for the given supplier.
    Does NOT modify the database.
    """

    def get(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)

        if not supplier.website_url:
            return JsonResponse({"error": "No website URL set for this supplier."}, status=400)

        from .utils import scrape_supplier_site

        suggestions = scrape_supplier_site(supplier.website_url) or {}

        payload = {
            "suggestions": {
                "logo_url": {
                    "current": supplier.logo_url,
                    "suggested": suggestions.get("logo_url"),
                },
                "primary_phone": {
                    "current": supplier.primary_phone or supplier.business_phone,
                    "suggested": suggestions.get("primary_phone"),
                },
                "primary_email": {
                    "current": supplier.primary_email or supplier.business_email,
                    "suggested": suggestions.get("primary_email"),
                },
                "address": {
                    "current": supplier.shipping_address or supplier.billing_address,
                    "suggested": suggestions.get("address"),
                },
            }
        }

        return JsonResponse(payload)


class SupplierApplyEnrichmentView(LoginRequiredMixin, View):
    """
    POST: apply a single suggested field (e.g. primary_phone) for a supplier.
    Expects JSON: {"field": "<field_name>", "value": "<new_value>"}
    """

    def post(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)

        try:
            data = json.loads(request.body.decode("utf-8"))
        except ValueError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        field = data.get("field")
        value = data.get("value")

        allowed_fields = ["logo_url", "primary_phone", "primary_email", "website_url"]

        if field not in allowed_fields and field != "address":
            return JsonResponse({"error": "Field not allowed"}, status=400)

        if field == "address":
            # Map suggested address to shipping_address for now
            supplier.shipping_address = value
            update_fields = ["shipping_address", "last_enriched_at"]
        else:
            setattr(supplier, field, value)
            update_fields = [field, "last_enriched_at"]

        supplier.last_enriched_at = timezone.now()
        supplier.save(update_fields=update_fields)

        return JsonResponse({"ok": True})


class SupplierEnrichPageView(LoginRequiredMixin, TemplateView):
    template_name = 'suppliers/supplier_enrich.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supplier = get_object_or_404(Supplier, pk=kwargs.get("pk"))
        context['supplier'] = supplier
        return context


def supplier_search_api(request):
    term = request.GET.get('q', '').strip()
    qs = Supplier.objects.all()
    if term:
        qs = qs.filter(
            Q(name__icontains=term)
            | Q(cage_code__icontains=term)
            | Q(contract__contract_number__icontains=term)
        )
    qs = qs.order_by('name')[:15]
    results = [
        {
            'supplier_name': s.name or '',
            'cage_code': s.cage_code or '',
            'supplier_id': s.id,
        }
        for s in qs
    ]
    return JsonResponse({'results': results})
