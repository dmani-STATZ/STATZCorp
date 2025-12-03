from django.db import models
from django.db.models import Q, Count, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.views.generic import TemplateView, DetailView

from contracts.models import Contract
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
