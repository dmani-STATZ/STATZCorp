from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import UpdateView, ListView, DetailView, CreateView
from django.contrib import messages
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.http import HttpResponseRedirect, JsonResponse
from django.db.models import Q, Count, Sum, Case, When, DecimalField
from django.db import DatabaseError
from django.utils import timezone
from datetime import timedelta, datetime

from STATZWeb.decorators import conditional_login_required
from suppliers.models import (
    Supplier,
    Contact,
    SupplierCertification,
    SupplierClassification,
    CertificationType,
    ClassificationType,
    SupplierType,
    SupplierDocument,
)
from ..models import (
    Address,
    Contract,
    Clin,
    SpecialPaymentTerms,
)
from ..forms import SupplierForm


def parse_date_input(value):
    """
    Parse common date strings (HTML date inputs, ISO strings) into aware datetimes.
    Returns None when empty or invalid.
    """
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None

    parsed = None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


@method_decorator(conditional_login_required, name='dispatch')
class SupplierListView(ListView):
    model = Supplier
    template_name = 'suppliers/supplier_list.html'
    context_object_name = 'suppliers'
    paginate_by = None
    ajax_required_fields = ['id', 'name', 'cage_code']

    def get_queryset(self):
        queryset = Supplier.objects.all()
        
        # Get search parameters
        name = self.request.GET.get('name', '').strip()
        cage_code = self.request.GET.get('cage_code', '').strip()
        q = self.request.GET.get('q', '').strip()
        certification_type = self.request.GET.get('certification')
        archived_filter = self.request.GET.get('archived', 'active')
        probation = self.request.GET.get('probation') == 'true'
        conditional = self.request.GET.get('conditional') == 'true'
        iso = self.request.GET.get('iso') == 'true'
        ppi = self.request.GET.get('ppi') == 'true'
        
        # Apply filters
        if name:
            queryset = queryset.filter(name__icontains=name)
        if cage_code:
            queryset = queryset.filter(cage_code__icontains=cage_code)
        if q:
            queryset = queryset.filter(Q(name__icontains=q) | Q(cage_code__icontains=q))
        if probation:
            queryset = queryset.filter(probation=True)
        if conditional:
            queryset = queryset.filter(conditional=True)
        if iso:
            queryset = queryset.filter(iso=True)
        if ppi:
            queryset = queryset.filter(ppi=True)
        if certification_type:
            queryset = queryset.filter(
                suppliercertification__certification_type_id=certification_type
            )
        if archived_filter == 'archived':
            queryset = queryset.filter(archived=True)
        elif archived_filter == 'all':
            # No filter, include everything
            pass
        else:
            queryset = queryset.filter(archived=False)
        
        return queryset.order_by('name').distinct()

    @staticmethod
    def build_detail_payload(supplier):
        if not supplier:
            return {}

        def format_address(addr):
            if not addr:
                return None
            parts = [
                addr.address_line_1,
                addr.address_line_2,
                f"{addr.city}, {addr.state} {addr.zip}"
            ]
            return "\n".join([p for p in parts if p])

        def format_address_single_line(addr):
            if not addr:
                return None
            parts = [
                addr.address_line_1,
                addr.address_line_2,
                f"{addr.city}, {addr.state} {addr.zip}".strip()
            ]
            return ", ".join([p for p in parts if p])

        def as_dict(addr):
            if not addr:
                return None
            return {
                'id': addr.id,
                'line1': addr.address_line_1,
                'line2': addr.address_line_2,
                'city': addr.city,
                'state': addr.state,
                'zip': addr.zip,
                'display': format_address_single_line(addr)
            }

        contracts_qs = Contract.objects.filter(clin__supplier=supplier).select_related('idiq_contract', 'status').distinct().order_by('-created_on')
        contracts = contracts_qs[:10]
        contacts = list(Contact.objects.filter(supplier=supplier))
        if supplier.contact and supplier.contact not in contacts:
            contacts.append(supplier.contact)
        certifications = SupplierCertification.objects.filter(supplier=supplier)
        classifications = SupplierClassification.objects.filter(supplier=supplier)
        try:
            documents = SupplierDocument.objects.filter(supplier=supplier).select_related('certification', 'classification')
        except DatabaseError:
            documents = SupplierDocument.objects.none()
        now = timezone.now()
        year_ago = now - timedelta(days=365)
        contract_stats = {
            'total_contracts': contracts_qs.count(),
            'active_contracts': contracts_qs.filter(status__description='Open').count(),
            'total_value': Clin.objects.filter(supplier=supplier).aggregate(
                total=Sum('quote_value', output_field=DecimalField())
            )['total'] or 0,
            'yearly_value': Clin.objects.filter(
                supplier=supplier,
                contract__created_on__gte=year_ago
            ).aggregate(
                total=Sum('quote_value', output_field=DecimalField())
            )['total'] or 0,
        }

        address = None
        if supplier.physical_address:
            addr = supplier.physical_address
            address = ", ".join(filter(None, [
                addr.address_line_1,
                addr.address_line_2,
                f"{addr.city}, {addr.state} {addr.zip}"
            ]))

        def fmt_dt(dt):
            return dt.strftime('%Y-%m-%d %H:%M') if dt else None

        doc_map_cert = {}
        doc_map_class = {}
        def get_file_bits(doc):
            try:
                url = doc.file.url
            except Exception:
                url = ''
            name = doc.file.name if doc.file else ''
            return url, name

        for doc in documents:
            url, name = get_file_bits(doc)
            if doc.certification_id and doc.certification_id not in doc_map_cert:
                doc_map_cert[doc.certification_id] = (doc, url, name)
            if doc.classification_id and doc.classification_id not in doc_map_class:
                doc_map_class[doc.classification_id] = (doc, url, name)

        return {
            'id': supplier.id,
            'name': supplier.name,
            'cage_code': supplier.cage_code,
            'dodaac': supplier.dodaac,
            'supplier_type': supplier.supplier_type.description if supplier.supplier_type else '',
            'supplier_type_id': supplier.supplier_type.id if supplier.supplier_type else None,
            'is_packhouse': bool(supplier.is_packhouse),
            'packhouse': supplier.packhouse.cage_code if supplier.packhouse else '',
            'packhouse_id': supplier.packhouse.id if supplier.packhouse else None,
            'probation': bool(supplier.probation),
            'probation_on': fmt_dt(supplier.probation_on),
            'probation_by': supplier.probation_by.username if supplier.probation_by else None,
            'conditional': bool(supplier.conditional),
            'conditional_on': fmt_dt(supplier.conditional_on),
            'conditional_by': supplier.conditional_by.username if supplier.conditional_by else None,
            'archived': bool(supplier.archived),
            'archived_on': fmt_dt(supplier.archived_on),
            'archived_by': supplier.archived_by.username if supplier.archived_by else None,
            'business_phone': supplier.business_phone,
            'business_fax': supplier.business_fax,
            'business_email': supplier.business_email,
            'address': address,
            'billing_address': format_address(supplier.billing_address),
            'shipping_address': format_address(supplier.shipping_address),
            'physical_address': format_address(supplier.physical_address),
            'billing_address_id': supplier.billing_address.id if supplier.billing_address else None,
            'shipping_address_id': supplier.shipping_address.id if supplier.shipping_address else None,
            'physical_address_id': supplier.physical_address.id if supplier.physical_address else None,
            'billing_address_display': format_address_single_line(supplier.billing_address),
            'shipping_address_display': format_address_single_line(supplier.shipping_address),
            'physical_address_display': format_address_single_line(supplier.physical_address),
            'billing_address_obj': as_dict(supplier.billing_address),
            'shipping_address_obj': as_dict(supplier.shipping_address),
            'physical_address_obj': as_dict(supplier.physical_address),
            'contact_name': supplier.contact.name if supplier.contact else None,
            'contact_email': supplier.contact.email if supplier.contact else None,
            'contact_phone': supplier.contact.phone if supplier.contact else None,
            'special_terms': supplier.special_terms.terms if supplier.special_terms else None,
            'special_terms_id': supplier.special_terms.id if supplier.special_terms else None,
            'special_terms_on': fmt_dt(supplier.special_terms_on),
            'prime': supplier.prime,
            'ppi': bool(supplier.ppi),
            'iso': bool(supplier.iso),
            'allows_gsi': supplier.get_allows_gsi_display() if hasattr(supplier, 'get_allows_gsi_display') else None,
            'allows_gsi_value': supplier.allows_gsi,
            'files_url': supplier.files_url,
            'notes': supplier.notes or '',
            'certifications': [
                {
                    'type': cert.certification_type.name,
                    'id': cert.id,
                    'date': cert.certification_date.strftime('%Y-%m-%d') if cert.certification_date else None,
                    'expires': cert.certification_expiration.strftime('%Y-%m-%d') if cert.certification_expiration else None,
                    'compliance_status': cert.compliance_status,
                    'document_id': doc_map_cert.get(cert.id)[0].id if doc_map_cert.get(cert.id) else None,
                    'document_url': doc_map_cert.get(cert.id)[1] if doc_map_cert.get(cert.id) else None,
                    'document_name': doc_map_cert.get(cert.id)[2] if doc_map_cert.get(cert.id) else None,
                } for cert in certifications
            ],
            'classifications': [
                {
                    'type': c.classification_type.name,
                    'id': c.id,
                    'date': c.classification_date.strftime('%Y-%m-%d') if c.classification_date else None,
                    'expires': c.classification_expiration.strftime('%Y-%m-%d') if c.classification_expiration else None,
                    'document_id': doc_map_class.get(c.id)[0].id if doc_map_class.get(c.id) else None,
                    'document_url': doc_map_class.get(c.id)[1] if doc_map_class.get(c.id) else None,
                    'document_name': doc_map_class.get(c.id)[2] if doc_map_class.get(c.id) else None,
                } for c in classifications
            ],
            'contracts': [
                {
                    'number': c.contract_number,
                    'status': c.status.description if c.status else '',
                    'award_date': c.award_date.strftime('%Y-%m-%d') if c.award_date else None
                } for c in contracts
            ],
            'contacts': [
                {
                    'id': ct.id,
                    'name': ct.name,
                    'title': ct.title,
                    'email': ct.email,
                    'phone': ct.phone
                } for ct in contacts
            ],
            'stats': contract_stats,
            'documents': [
                {
                    'id': doc.id,
                    'doc_type': doc.doc_type,
                    'description': doc.description,
                    'certification_id': doc.certification_id,
                    'classification_id': doc.classification_id,
                    'file_name': get_file_bits(doc)[1],
                    'file_url': get_file_bits(doc)[0],
                } for doc in documents
            ],
        }

    def render_to_response(self, context, **response_kwargs):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            supplier_id = self.request.GET.get('supplier_id')
            supplier = None
            if supplier_id:
                supplier = Supplier.objects.filter(pk=supplier_id).first()
            payload = self.build_detail_payload(supplier)
            return JsonResponse(payload, safe=False)
        return super().render_to_response(context, **response_kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['certification_types'] = CertificationType.objects.all().order_by('name')
        context['archived_filter'] = self.request.GET.get('archived', 'active')
        
        suppliers = context.get('suppliers') or []
        selected_supplier = None
        supplier_id = self.request.GET.get('supplier_id')
        if supplier_id:
            try:
                # Prefer the supplier from current page of results; fallback to direct lookup for deep links
                selected_supplier = suppliers.filter(pk=supplier_id).first()
                if not selected_supplier:
                    selected_supplier = Supplier.objects.filter(pk=supplier_id).first()
            except Exception:
                selected_supplier = None

        contracts = Contract.objects.none()
        contacts = Contact.objects.none()
        certifications = SupplierCertification.objects.none()
        classifications = SupplierClassification.objects.none()
        contract_stats = {}

        if selected_supplier:
            payload = self.build_detail_payload(selected_supplier)
        else:
            payload = {}

        suppliers_qs = context.get('suppliers') or Supplier.objects.none()
        if hasattr(suppliers_qs, 'values'):
            initial_suppliers = list(suppliers_qs.values('id', 'name', 'cage_code')[:200])
        else:
            initial_suppliers = [{'id': s.id, 'name': s.name, 'cage_code': s.cage_code} for s in suppliers_qs[:200]]

        context.update({
            'selected_supplier': selected_supplier,
            'has_selected_supplier': selected_supplier is not None,
            'detail_payload': payload,
            'detail_contracts': payload.get('contracts', []),
            'detail_contacts': payload.get('contacts', []),
            'detail_certifications': payload.get('certifications', []),
            'detail_classifications': payload.get('classifications', []),
            'detail_stats': payload.get('stats', {}),
            'active_tab': self.request.GET.get('tab', 'info'),
            'supplier_types': SupplierType.objects.all().order_by('description'),
            'packhouse_options': Supplier.objects.filter(
                Q(is_packhouse=True) | Q(supplier_type__description__iexact='packhouse')
            ).order_by('name'),
            'special_terms_options': SpecialPaymentTerms.objects.all().order_by('terms'),
            'certification_types': CertificationType.objects.all().order_by('name'),
            'classification_types': ClassificationType.objects.all().order_by('name'),
            'initial_suppliers': initial_suppliers,
            'compliance_statuses': SupplierCertification.objects.exclude(
                compliance_status__isnull=True
            ).exclude(
                compliance_status__exact=''
            ).values_list('compliance_status', flat=True).distinct().order_by('compliance_status'),
            'today': timezone.localdate(),
        })
        return context


@conditional_login_required
def toggle_supplier_flag(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
    field = request.POST.get('field')
    if field not in ['probation', 'conditional', 'archived']:
        return JsonResponse({'error': 'Invalid field'}, status=400)
    supplier = get_object_or_404(Supplier, pk=pk)
    now = timezone.now()
    user = request.user

    def clear(field_name, on_attr, by_attr):
        setattr(supplier, field_name, False)
        setattr(supplier, on_attr, None)
        setattr(supplier, by_attr, None)

    def set_flag(field_name, on_attr, by_attr):
        setattr(supplier, field_name, True)
        setattr(supplier, on_attr, now)
        setattr(supplier, by_attr, user)

    if field == 'probation':
        if supplier.probation:
            clear('probation', 'probation_on', 'probation_by')
        else:
            set_flag('probation', 'probation_on', 'probation_by')
    elif field == 'conditional':
        if supplier.conditional:
            clear('conditional', 'conditional_on', 'conditional_by')
        else:
            set_flag('conditional', 'conditional_on', 'conditional_by')
    elif field == 'archived':
        if supplier.archived:
            clear('archived', 'archived_on', 'archived_by')
        else:
            set_flag('archived', 'archived_on', 'archived_by')

    supplier.save()
    payload = SupplierListView.build_detail_payload(supplier)
    return JsonResponse(payload, safe=False)


@conditional_login_required
def update_supplier_header(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)

    supplier = get_object_or_404(Supplier, pk=pk)
    name = (request.POST.get('name') or '').strip()
    cage_code = (request.POST.get('cage_code') or '').strip()
    dodaac = (request.POST.get('dodaac') or '').strip()

    supplier.name = name or None
    supplier.cage_code = cage_code or None
    supplier.dodaac = dodaac or None
    supplier.modified_by = request.user
    supplier.save(update_fields=['name', 'cage_code', 'dodaac', 'modified_by', 'modified_on'])

    payload = SupplierListView.build_detail_payload(supplier)
    return JsonResponse(payload, safe=False)


@conditional_login_required
def update_supplier_notes(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
    supplier = get_object_or_404(Supplier, pk=pk)
    notes = request.POST.get('notes', '')
    supplier.notes = notes
    supplier.modified_by = request.user
    supplier.save(update_fields=['notes', 'modified_by', 'modified_on'])
    payload = SupplierListView.build_detail_payload(supplier)
    return JsonResponse(payload, safe=False)


@conditional_login_required
def update_supplier_files(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
    supplier = get_object_or_404(Supplier, pk=pk)
    files_url = request.POST.get('files_url', '').strip()
    supplier.files_url = files_url or None
    supplier.modified_by = request.user
    supplier.save(update_fields=['files_url', 'modified_by', 'modified_on'])
    payload = SupplierListView.build_detail_payload(supplier)
    return JsonResponse(payload, safe=False)


@conditional_login_required
def update_supplier_selects(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
    supplier = get_object_or_404(Supplier, pk=pk)
    supplier_type_id = request.POST.get('supplier_type_id')
    packhouse_id = request.POST.get('packhouse_id')

    if supplier_type_id:
        supplier.supplier_type = SupplierType.objects.filter(pk=supplier_type_id).first()
    else:
        supplier.supplier_type = None
    if packhouse_id is not None:
        supplier.packhouse = Supplier.objects.filter(pk=packhouse_id).first() if packhouse_id else None

    supplier.modified_by = request.user
    supplier.save(update_fields=['supplier_type', 'packhouse', 'modified_by', 'modified_on'])
    payload = SupplierListView.build_detail_payload(supplier)
    return JsonResponse(payload, safe=False)


@conditional_login_required
def update_supplier_compliance(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
    supplier = get_object_or_404(Supplier, pk=pk)
    prime_val = request.POST.get('prime')
    ppi_val = request.POST.get('ppi')
    iso_val = request.POST.get('iso')
    gsi_val = request.POST.get('allows_gsi')
    special_terms_id = request.POST.get('special_terms_id')

    supplier.prime = int(prime_val) if prime_val else None
    if ppi_val in ['true', 'false']:
        supplier.ppi = True if ppi_val == 'true' else False
    if iso_val in ['true', 'false']:
        supplier.iso = True if iso_val == 'true' else False
    if gsi_val in ['YES', 'NO', 'UNK']:
        supplier.allows_gsi = gsi_val
    if special_terms_id:
        supplier.special_terms = SpecialPaymentTerms.objects.filter(pk=special_terms_id).first()
        supplier.special_terms_on = timezone.now()
    else:
        supplier.special_terms = None
        supplier.special_terms_on = None

    supplier.modified_by = request.user
    supplier.save(update_fields=['prime', 'ppi', 'iso', 'allows_gsi', 'special_terms', 'special_terms_on', 'modified_by', 'modified_on'])
    payload = SupplierListView.build_detail_payload(supplier)
    return JsonResponse(payload, safe=False)


@conditional_login_required
def addresses_lookup(request):
    q = (request.GET.get('q') or '').strip()
    addresses = Address.objects.all()
    if q:
        addresses = addresses.filter(
            Q(address_line_1__icontains=q) |
            Q(address_line_2__icontains=q) |
            Q(city__icontains=q) |
            Q(state__icontains=q) |
            Q(zip__icontains=q)
        )
    addresses = addresses.order_by('-id')[:50]
    results = []
    for addr in addresses:
        parts = [addr.address_line_1, addr.address_line_2, f"{addr.city}, {addr.state} {addr.zip}"]
        display = ", ".join([p for p in parts if p])
        results.append({
            'id': addr.id,
            'line1': addr.address_line_1,
            'line2': addr.address_line_2,
            'city': addr.city,
            'state': addr.state,
            'zip': addr.zip,
            'display': display,
        })
    return JsonResponse({'results': results})


@conditional_login_required
def update_supplier_address(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
    supplier = get_object_or_404(Supplier, pk=pk)
    field = request.POST.get('field')
    if field not in ['physical', 'shipping', 'billing']:
        return JsonResponse({'error': 'Invalid field'}, status=400)

    address_id = request.POST.get('address_id')
    line1 = (request.POST.get('line1') or '').strip()
    line2 = (request.POST.get('line2') or '').strip()
    city = (request.POST.get('city') or '').strip()
    state = (request.POST.get('state') or '').strip()
    zip_code = (request.POST.get('zip') or '').strip()

    address_obj = None
    if address_id:
        address_obj = Address.objects.filter(pk=address_id).first()
        if address_obj and (line1 or line2 or city or state or zip_code):
            address_obj.address_line_1 = line1 or address_obj.address_line_1
            address_obj.address_line_2 = line2 or address_obj.address_line_2
            address_obj.city = city or address_obj.city
            address_obj.state = state or address_obj.state
            address_obj.zip = zip_code or address_obj.zip
            address_obj.save()
    elif line1 or city or state or zip_code:
        address_obj = Address.objects.create(
            address_line_1=line1,
            address_line_2=line2 or None,
            city=city,
            state=state,
            zip=zip_code
        )

    if not address_obj:
        return JsonResponse({'error': 'No address data provided'}, status=400)

    if field == 'physical':
        supplier.physical_address = address_obj
    elif field == 'shipping':
        supplier.shipping_address = address_obj
    elif field == 'billing':
        supplier.billing_address = address_obj

    supplier.modified_by = request.user
    supplier.save(update_fields=['physical_address', 'shipping_address', 'billing_address', 'modified_by', 'modified_on'])
    payload = SupplierListView.build_detail_payload(supplier)
    return JsonResponse(payload, safe=False)


@conditional_login_required
def save_supplier_contact(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
    supplier = get_object_or_404(Supplier, pk=pk)
    contact_id = request.POST.get('contact_id')
    name = (request.POST.get('name') or '').strip()
    email = (request.POST.get('email') or '').strip()
    phone = (request.POST.get('phone') or '').strip()
    title = (request.POST.get('title') or '').strip()

    if not name:
        return JsonResponse({'error': 'Name is required'}, status=400)

    if contact_id:
        contact = get_object_or_404(Contact, pk=contact_id)
        if contact.supplier and contact.supplier != supplier:
            return JsonResponse({'error': 'Contact belongs to another supplier'}, status=403)
    else:
        contact = Contact()

    contact.supplier = supplier
    contact.name = name
    contact.email = email or None
    contact.phone = phone or None
    contact.title = title or None
    contact.save()

    if not supplier.contact:
        supplier.contact = contact
        supplier.save(update_fields=['contact'])

    payload = SupplierListView.build_detail_payload(supplier)
    return JsonResponse(payload, safe=False)


@conditional_login_required
def delete_supplier_contact(request, pk, contact_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
    supplier = get_object_or_404(Supplier, pk=pk)
    contact = get_object_or_404(Contact, pk=contact_id, supplier=supplier)

    if supplier.contact_id == contact.id:
        supplier.contact = None
        supplier.save(update_fields=['contact'])

    contact.delete()
    payload = SupplierListView.build_detail_payload(supplier)
    return JsonResponse(payload, safe=False)


@method_decorator(conditional_login_required, name='dispatch')
class SupplierSearchView(ListView):
    model = Supplier
    template_name = 'suppliers/supplier_search.html'
    context_object_name = 'suppliers'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = Supplier.objects.all()
        
        # Get search parameters
        name = self.request.GET.get('name', '').strip()
        cage_code = self.request.GET.get('cage_code', '').strip()
        q = self.request.GET.get('q', '').strip()
        archived_filter = self.request.GET.get('archived', 'active')
        probation = self.request.GET.get('probation') == 'true'
        conditional = self.request.GET.get('conditional') == 'true'
        iso = self.request.GET.get('iso') == 'true'
        ppi = self.request.GET.get('ppi') == 'true'
        
        # Apply filters
        if name:
            queryset = queryset.filter(name__icontains=name)
        if cage_code:
            queryset = queryset.filter(cage_code__icontains=cage_code)
        if q:
            queryset = queryset.filter(Q(name__icontains=q) | Q(cage_code__icontains=q))
        if probation:
            queryset = queryset.filter(probation=True)
        if conditional:
            queryset = queryset.filter(conditional=True)
        if iso:
            queryset = queryset.filter(iso=True)
        if ppi:
            queryset = queryset.filter(ppi=True)
        if archived_filter == 'archived':
            queryset = queryset.filter(archived=True)
        elif archived_filter == 'all':
            pass
        else:
            queryset = queryset.filter(archived=False)
        
        return queryset.order_by('name')


@method_decorator(conditional_login_required, name='dispatch')
class SupplierDetailView(DetailView):
    model = Supplier
    template_name = 'suppliers/legacy_supplier_detail.html'
    context_object_name = 'supplier'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supplier = self.object
        
        # Get related contracts
        contracts = Contract.objects.filter(
            clin__supplier=supplier
        ).select_related('idiq_contract', 'status').distinct().order_by('-created_on')
        
        # Get related contacts
        contacts = Contact.objects.filter(supplier=supplier)
        
        # Get QMS certifications and classifications
        certifications = SupplierCertification.objects.filter(supplier=supplier)
        classifications = SupplierClassification.objects.filter(supplier=supplier)
        
        # Get certification and classification types
        certification_types = CertificationType.objects.all()
        classification_types = ClassificationType.objects.all()
        
        # Calculate statistics
        now = timezone.now()
        year_ago = now - timedelta(days=365)
        
        contract_stats = {
            'total_contracts': contracts.count(),
            'active_contracts': contracts.filter(status__description='Open').count(),
            'total_value': Clin.objects.filter(supplier=supplier).aggregate(
                total=Sum('quote_value', output_field=DecimalField())
            )['total'] or 0,
            'yearly_value': Clin.objects.filter(
                supplier=supplier,
                contract__created_on__gte=year_ago
            ).aggregate(
                total=Sum('quote_value', output_field=DecimalField())
            )['total'] or 0,
        }
        
        # Add all data to context
        context.update({
            'contracts': contracts,
            'contacts': contacts,
            'certifications': certifications,
            'classifications': classifications,
            'certification_types': certification_types,
            'classification_types': classification_types,
            'contract_stats': contract_stats,
            'active_tab': self.request.GET.get('tab', 'info'),
        })
        
        return context


@method_decorator(conditional_login_required, name='dispatch')
class SupplierCreateView(CreateView):
    model = Supplier
    template_name = 'suppliers/supplier_form.html'
    form_class = SupplierForm
    success_url = reverse_lazy('suppliers:supplier_list')
    
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Supplier {form.instance.name} created successfully!")
        return response


@method_decorator(conditional_login_required, name='dispatch')
class SupplierUpdateView(UpdateView):
    model = Supplier
    template_name = 'suppliers/supplier_edit.html'
    context_object_name = 'supplier'
    form_class = SupplierForm
    
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        # Store the original data in the instance for comparison
        obj._original_data = {
            'name': obj.name,
            'cage_code': obj.cage_code,
            'supplier_type': obj.supplier_type,
            'physical_address': obj.physical_address,
            'shipping_address': obj.shipping_address,
            'billing_address': obj.billing_address,
            'business_phone': obj.business_phone,
            'business_fax': obj.business_fax,
            'business_email': obj.business_email,
            'primary_phone': getattr(obj, 'primary_phone', None),
            'primary_email': getattr(obj, 'primary_email', None),
            'website_url': getattr(obj, 'website_url', None),
            'logo_url': getattr(obj, 'logo_url', None),
            'contact': obj.contact,
            'probation': obj.probation,
            'conditional': obj.conditional,
            'special_terms': obj.special_terms,
            'prime': obj.prime,
            'ppi': obj.ppi,
            'iso': obj.iso,
            'notes': obj.notes,
            'allows_gsi': obj.allows_gsi,
            'is_packhouse': obj.is_packhouse,
            'packhouse': obj.packhouse,
            'archived': obj.archived,
        }
        return obj
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        supplier = self.get_object()
        
        # Set initial data from the stored original data
        initial_data = {
            'name': supplier.name,
            'cage_code': supplier.cage_code,
            'supplier_type': supplier.supplier_type.id if supplier.supplier_type else None,
            'physical_address': supplier.physical_address.id if supplier.physical_address else None,
            'shipping_address': supplier.shipping_address.id if supplier.shipping_address else None,
            'billing_address': supplier.billing_address.id if supplier.billing_address else None,
            'business_phone': supplier.business_phone,
            'business_fax': supplier.business_fax,
            'business_email': supplier.business_email,
            'primary_phone': supplier.primary_phone,
            'primary_email': supplier.primary_email,
            'website_url': supplier.website_url,
            'logo_url': supplier.logo_url,
            'contact': supplier.contact.id if supplier.contact else None,
            'probation': supplier.probation,
            'conditional': supplier.conditional,
            'special_terms': supplier.special_terms.id if supplier.special_terms else None,
            'prime': supplier.prime,
            'ppi': supplier.ppi,
            'iso': supplier.iso,
            'notes': supplier.notes,
            'allows_gsi': supplier.allows_gsi,
            'is_packhouse': supplier.is_packhouse,
            'packhouse': supplier.packhouse.id if supplier.packhouse else None,
            'archived': supplier.archived,
        }
        
        # Handle auto-selection of newly created address
        new_address_id = self.request.GET.get('new_address_id')
        address_type = self.request.GET.get('address_type')
        if new_address_id and address_type:
            address_field = f'{address_type}_address'
            if address_field in initial_data:
                initial_data[address_field] = int(new_address_id)
        
        form.initial.update(initial_data)
        return form
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supplier = self.get_object()
        
        # Create a list to store all addresses we need
        all_needed_addresses = []
        
        # Add the supplier's assigned addresses to the list if they exist
        # Use a set to track unique IDs
        seen_address_ids = set()
        
        # If a new address was just created, add it first
        new_address_id = self.request.GET.get('new_address_id')
        address_type = self.request.GET.get('address_type')
        if new_address_id:
            try:
                new_address = Address.objects.get(id=new_address_id)
                all_needed_addresses.append(new_address)
                seen_address_ids.add(new_address.id)
                # Set a flag to show success message
                type_labels = {'physical': 'Physical', 'shipping': 'Shipping', 'billing': 'Billing'}
                context['new_address_message'] = f"New address created and selected as {type_labels.get(address_type, '')} Address"
            except Address.DoesNotExist:
                pass
        
        # Add addresses, ensuring no duplicates
        for address in [supplier.physical_address, supplier.shipping_address, supplier.billing_address]:
            if address and address.id not in seen_address_ids:
                all_needed_addresses.append(address)
                seen_address_ids.add(address.id)
            
        # Add 10 most recent addresses that aren't already included
        recent_addresses = Address.objects.exclude(id__in=seen_address_ids).order_by('-id')[:10]
        all_needed_addresses.extend(recent_addresses)
        
        # Add all addresses to context for display
        context['addresses'] = all_needed_addresses
        context['new_address_id'] = new_address_id
        context['address_type'] = address_type
        return context
    
    def form_valid(self, form):
        # If this is an AJAX request (for notes update)
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # Only update the notes field
            supplier = self.get_object()
            supplier.notes = form.cleaned_data['notes']
            supplier.save(update_fields=['notes'])
            return JsonResponse({
                'status': 'success',
                'message': f"Notes updated successfully for {supplier.name}",
                'notes': supplier.notes
            })
            
        # For regular form submission, ensure we're not losing data
        supplier = form.save(commit=False)
        original = self.get_object()._original_data
        
        # Only update fields that were actually in the form data
        for field, value in form.cleaned_data.items():
            if field in form.changed_data:
                setattr(supplier, field, value)
            else:
                # Keep the original value for unchanged fields
                setattr(supplier, field, original.get(field))

        def handle_flag(flag_name, date_attr, user_attr):
            if flag_name not in form.changed_data:
                return
            if form.cleaned_data.get(flag_name):
                setattr(supplier, flag_name, True)
                setattr(supplier, date_attr, timezone.now())
                setattr(supplier, user_attr, self.request.user)
            else:
                setattr(supplier, flag_name, False)
                setattr(supplier, date_attr, None)
                setattr(supplier, user_attr, None)

        handle_flag('probation', 'probation_on', 'probation_by')
        handle_flag('conditional', 'conditional_on', 'conditional_by')

        if 'archived' in form.changed_data:
            if form.cleaned_data.get('archived'):
                supplier.archived_on = timezone.now()
                supplier.archived_by = self.request.user
            else:
                supplier.archived_on = None
                supplier.archived_by = None
        
        # Ensure boolean fields without tracking are set to False instead of None
        for bool_field in ['ppi', 'iso', 'is_packhouse']:
            if bool_field in form.changed_data:
                value = form.cleaned_data.get(bool_field)
                # Convert None to False
                setattr(supplier, bool_field, bool(value))

        supplier.save()
        messages.success(self.request, f"Supplier {supplier.name} updated successfully!")
        return HttpResponseRedirect(self.get_success_url())
    
    def form_invalid(self, form):
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error',
                'message': 'Failed to update notes. Please check your input.',
                'errors': form.errors
            }, status=400)
        return super().form_invalid(form)
    
    def get_success_url(self):
        if 'contract_id' in self.kwargs:
            return reverse('contracts:contract_management', kwargs={'pk': self.kwargs['contract_id']})
        return reverse('suppliers:supplier_detail', kwargs={'pk': self.object.pk})


# Certification Views
@conditional_login_required
def add_supplier_certification(request, supplier_id):
    if request.method == 'POST':
        print(f"DEBUG - Received POST request for supplier_id: {supplier_id}")
        print(f"DEBUG - POST data: {request.POST}")
        
        supplier = get_object_or_404(Supplier, id=supplier_id)
        certification_type = get_object_or_404(CertificationType, id=request.POST.get('certification_type'))
        cert_date_raw = request.POST.get('certification_date')
        cert_exp_raw = request.POST.get('certification_expiration')
        cert_date = parse_date_input(cert_date_raw)
        cert_exp = parse_date_input(cert_exp_raw)
        compliance_status = (request.POST.get('compliance_status') or '').strip() or None
        file_obj = request.FILES.get('file')

        if cert_date_raw and cert_date is None:
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid certification date. Use YYYY-MM-DD.'
            }, status=400)
        if cert_exp_raw and cert_exp is None:
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid certification expiration. Use YYYY-MM-DD.'
            }, status=400)
        if cert_date and cert_date.date() > timezone.localdate():
            return JsonResponse({
                'status': 'error',
                'message': 'Certification date cannot be in the future.'
            }, status=400)
        
        print(f"DEBUG - Creating certification with:")
        print(f"DEBUG - Supplier: {supplier}")
        print(f"DEBUG - Type: {certification_type}")
        print(f"DEBUG - Date: {cert_date_raw}")
        print(f"DEBUG - Expiration: {cert_exp_raw}")
        
        try:
            certification = SupplierCertification.objects.create(
                supplier=supplier,
                certification_type=certification_type,
                certification_date=cert_date,
                certification_expiration=cert_exp,
                compliance_status=compliance_status
            )
            if file_obj:
                SupplierDocument.objects.create(
                    supplier=supplier,
                    certification=certification,
                    doc_type='CERT',
                    file=file_obj,
                    description=f"{certification_type.name} certification document",
                    created_by=request.user if hasattr(request, 'user') else None,
                )
            print(f"DEBUG - Successfully created certification: {certification}")
            return JsonResponse({
                'status': 'success',
                'message': 'Certification added successfully',
                'id': certification.id
            })
        except Exception as e:
            print(f"DEBUG - Error creating certification: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': f'Error creating certification: {str(e)}'
            }, status=400)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

@conditional_login_required
def delete_supplier_certification(request, supplier_id, pk):
    if request.method == 'POST':
        certification = get_object_or_404(SupplierCertification, id=pk, supplier_id=supplier_id)
        certification.delete()
        return JsonResponse({
            'status': 'success',
            'message': 'Certification deleted successfully'
        })
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

@conditional_login_required
def get_supplier_certification(request, pk):
    certification = get_object_or_404(SupplierCertification, id=pk)
    return JsonResponse({
        'id': certification.id,
        'certification_type': certification.certification_type.id,
        'compliance_status': certification.compliance_status,
        'certification_date': certification.certification_date.strftime('%Y-%m-%d') if certification.certification_date else None,
        'certification_expiration': certification.certification_expiration.strftime('%Y-%m-%d') if certification.certification_expiration else None
    })

@conditional_login_required
def update_supplier_certification(request, supplier_id, pk):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

    supplier = get_object_or_404(Supplier, id=supplier_id)
    certification = get_object_or_404(SupplierCertification, id=pk, supplier=supplier)
    certification_type = get_object_or_404(CertificationType, id=request.POST.get('certification_type'))
    cert_date_raw = request.POST.get('certification_date')
    cert_exp_raw = request.POST.get('certification_expiration')
    cert_date = parse_date_input(cert_date_raw)
    cert_exp = parse_date_input(cert_exp_raw)
    compliance_status = (request.POST.get('compliance_status') or '').strip() or None
    file_obj = request.FILES.get('file')

    if cert_date_raw and cert_date is None:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid certification date. Use YYYY-MM-DD.'
        }, status=400)
    if cert_exp_raw and cert_exp is None:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid certification expiration. Use YYYY-MM-DD.'
        }, status=400)
    if cert_date and cert_date.date() > timezone.localdate():
        return JsonResponse({
            'status': 'error',
            'message': 'Certification date cannot be in the future.'
        }, status=400)

    certification.certification_type = certification_type
    certification.certification_date = cert_date
    certification.certification_expiration = cert_exp
    certification.compliance_status = compliance_status
    certification.save()

    if file_obj:
        doc = SupplierDocument.objects.filter(certification=certification).order_by('-id').first()
        if doc:
            doc.file = file_obj
            doc.doc_type = 'CERT'
            doc.description = f"{certification_type.name} certification document"
            if hasattr(doc, 'modified_by'):
                doc.modified_by = request.user
            doc.save()
        else:
            SupplierDocument.objects.create(
                supplier=supplier,
                certification=certification,
                doc_type='CERT',
                file=file_obj,
                description=f"{certification_type.name} certification document",
                created_by=request.user if hasattr(request, 'user') else None,
            )

    return JsonResponse({
        'status': 'success',
        'message': 'Certification updated successfully',
        'id': certification.id
    })

# Classification Views
@conditional_login_required
def add_supplier_classification(request, supplier_id):
    if request.method == 'POST':
        supplier = get_object_or_404(Supplier, id=supplier_id)
        classification_type = get_object_or_404(ClassificationType, id=request.POST.get('classification_type'))
        class_date_raw = request.POST.get('classification_date')
        class_exp_raw = request.POST.get('expiration_date')
        class_date = parse_date_input(class_date_raw)
        class_exp = parse_date_input(class_exp_raw)
        file_obj = request.FILES.get('file')

        if class_date_raw and class_date is None:
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid classification date. Use YYYY-MM-DD.'
            }, status=400)
        if class_exp_raw and class_exp is None:
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid classification expiration. Use YYYY-MM-DD.'
            }, status=400)
        if class_date and class_date.date() > timezone.localdate():
            return JsonResponse({
                'status': 'error',
                'message': 'Classification date cannot be in the future.'
            }, status=400)
        
        try:
            classification = SupplierClassification.objects.create(
                supplier=supplier,
                classification_type=classification_type,
                classification_date=class_date,
                classification_expiration=class_exp
            )
            if file_obj:
                SupplierDocument.objects.create(
                    supplier=supplier,
                    classification=classification,
                    doc_type='CLASS',
                    file=file_obj,
                    description=f"{classification_type.name} classification document",
                    created_by=request.user if hasattr(request, 'user') else None,
                )
        except Exception as exc:
            return JsonResponse({
                'status': 'error',
                'message': f'Error creating classification: {exc}'
            }, status=400)
        
        return JsonResponse({
            'status': 'success',
            'message': 'Classification added successfully',
            'id': classification.id
        })
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

@conditional_login_required
def delete_supplier_classification(request, supplier_id, pk):
    if request.method == 'POST':
        classification = get_object_or_404(SupplierClassification, id=pk, supplier_id=supplier_id)
        classification.delete()
        return JsonResponse({
            'status': 'success',
            'message': 'Classification deleted successfully'
        })
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

@conditional_login_required
def get_supplier_classification(request, pk):
    classification = get_object_or_404(SupplierClassification, id=pk)
    return JsonResponse({
        'id': classification.id,
        'classification_type': classification.classification_type.id,
        'classification_date': classification.classification_date.strftime('%Y-%m-%d') if classification.classification_date else None,
        'expiration_date': classification.classification_expiration.strftime('%Y-%m-%d') if classification.classification_expiration else None
    }) 

@conditional_login_required
def update_supplier_classification(request, supplier_id, pk):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

    supplier = get_object_or_404(Supplier, id=supplier_id)
    classification = get_object_or_404(SupplierClassification, id=pk, supplier=supplier)
    classification_type = get_object_or_404(ClassificationType, id=request.POST.get('classification_type'))
    class_date_raw = request.POST.get('classification_date')
    class_exp_raw = request.POST.get('expiration_date')
    class_date = parse_date_input(class_date_raw)
    class_exp = parse_date_input(class_exp_raw)
    file_obj = request.FILES.get('file')

    if class_date_raw and class_date is None:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid classification date. Use YYYY-MM-DD.'
        }, status=400)
    if class_exp_raw and class_exp is None:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid classification expiration. Use YYYY-MM-DD.'
        }, status=400)
    if class_date and class_date.date() > timezone.localdate():
        return JsonResponse({
            'status': 'error',
            'message': 'Classification date cannot be in the future.'
        }, status=400)

    classification.classification_type = classification_type
    classification.classification_date = class_date
    classification.classification_expiration = class_exp
    classification.save()

    if file_obj:
        doc = SupplierDocument.objects.filter(classification=classification).order_by('-id').first()
        if doc:
            doc.file = file_obj
            doc.doc_type = 'CLASS'
            doc.description = f"{classification_type.name} classification document"
            if hasattr(doc, 'modified_by'):
                doc.modified_by = request.user
            doc.save()
        else:
            SupplierDocument.objects.create(
                supplier=supplier,
                classification=classification,
                doc_type='CLASS',
                file=file_obj,
                description=f"{classification_type.name} classification document",
                created_by=request.user if hasattr(request, 'user') else None,
            )

    return JsonResponse({
        'status': 'success',
        'message': 'Classification updated successfully',
        'id': classification.id
    })


@conditional_login_required
def supplier_autocomplete(request):
    term = request.GET.get('q', '').strip()
    archived_filter = request.GET.get('archived', 'active')

    queryset = Supplier.objects.all()
    if archived_filter == 'active':
        queryset = queryset.filter(archived=False)
    elif archived_filter == 'archived':
        queryset = queryset.filter(archived=True)
    # 'all' returns everything

    if term:
        queryset = queryset.filter(Q(name__icontains=term) | Q(cage_code__icontains=term))

    results = list(
        queryset.order_by('name')[:10].values('id', 'name', 'cage_code')
    )
    return JsonResponse({'results': results})
