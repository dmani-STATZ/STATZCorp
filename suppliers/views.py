import json
import os
import re

from django.conf import settings
from django.db import models
from django.db.models import Q, Count, Sum, Case, When, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.utils import timezone
from django.views.generic import TemplateView, DetailView, View, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from urllib.parse import urlparse

from contracts.models import Contract, Clin, Address
from suppliers.models import (
    Supplier,
    SupplierDocument,
    SupplierType,
    SupplierCertification,
    SupplierClassification,
    CertificationType,
    ClassificationType,
)
import requests

from .openrouter_config import (
    get_model_for_request,
    get_openrouter_model_info,
    save_openrouter_model_config,
)

SUPPLIER_ENRICH_SYSTEM_PROMPT = (
    "You are a procurement data analyst. Extract structured supplier metadata from website HTML. "
    "Always respond with strict JSON (no markdown) matching this schema:\n"
    "{\n"
    '  "company_name": string | null,\n'
    '  "logo_url": string | null,\n'
    '  "addresses": [{"label": string, "value": string}, ...],\n'
    '  "phone_numbers": [{"label": string, "value": string}, ...],\n'
    '  "emails": [{"label": string, "value": string}, ...],\n'
    '  "cage_code": string | null,\n'
    '  "website_url": string | null,\n'
    '  "social_links": [{"label": string, "url": string}],\n'
    '  "notes": string | null\n'
    "}\n"
    "Return empty arrays when data is not found and null for missing scalars."
)

SUPPLIER_ENRICH_HTML_MAX_CHARS = 120000


def _parse_address_text(text: str) -> dict:
    """
    Best-effort parse of an address string into components.
    Handles common US formats like "123 Main St, Suite 5, City, ST 12345, Country"
    and multi-line inputs. Prefers the trailing ZIP/state pattern when present.
    Returns parts plus the original text.
    """
    if not text:
        return {"text": "", "line1": "", "line2": "", "city": "", "state": "", "postal_code": "", "country": ""}

    cleaned_text = text.strip()
    # Normalize newlines to commas to help parsing multi-line addresses.
    flat = re.sub(r"[\r\n]+", ", ", cleaned_text)
    flat = re.sub(r"\s+", " ", flat).strip(" ,")

    # Primary regex: line1, optional line2, city, state, zip, optional country
    main_re = re.compile(
        r"^(?P<line1>.+?),\s*(?:(?P<line2>[^,]+?),\s*)?(?P<city>[^,]+?),\s*(?P<state>[A-Za-z]{2})\s+(?P<postal>\d{5}(?:-\d{4})?)(?:\s*(?P<country>.+))?$"
    )
    m = main_re.match(flat)
    if m:
        return {
            "text": cleaned_text,
            "line1": m.group("line1").strip(),
            "line2": (m.group("line2") or "").strip(),
            "city": m.group("city").strip(),
            "state": m.group("state").strip(),
            "postal_code": m.group("postal").strip(),
            "country": (m.group("country") or "").strip(),
        }

    def clean(token):
        return token.strip().strip(",")

    parts = [clean(p) for p in flat.split(",") if clean(p)]
    line1 = parts[0] if parts else flat
    line2 = ""
    city = ""
    state = ""
    postal = ""
    country = ""

    # Try to find trailing ZIP (5 or 9) and state preceding it.
    zip_match = re.search(r"(\d{5}(?:-\d{4})?)\s*$", flat)
    if zip_match:
        postal = zip_match.group(1)
        before_zip = flat[: zip_match.start()].rstrip(" ,")
        # State is the last 2-letter token before zip
        state_match = re.search(r"([A-Za-z]{2})\s*$", before_zip)
        if state_match:
            state = state_match.group(1)
            city_part = before_zip[: state_match.start()].rstrip(" ,")
            # City is the last comma-delimited segment before state
            city_tokens = [p for p in city_part.split(",") if p.strip()]
            if city_tokens:
                city = city_tokens[-1].strip()
                # line1/line2 from earlier segments if available
                if city_tokens[:-1]:
                    line1 = city_tokens[0].strip()
                    if len(city_tokens) > 2:
                        line2 = city_tokens[1].strip()
            else:
                city = city_part.strip()

    # If last token looks like a country (words, not 2-letter state+zip), separate it
    if parts:
        maybe_country = parts[-1]
        if len(maybe_country) > 2 and not re.match(r"^[A-Za-z]{2}\s+\d{5}", maybe_country):
            country = maybe_country
            parts = parts[:-1]

    # Check the tail for "ST 12345" even if it's at the end without a comma
    if parts:
        tail = parts[-1]
        tail_match = re.match(r"^(?P<state>[A-Za-z]{2})\s+(?P<postal>\d{5}(?:-\d{4})?)$", tail)
        if tail_match:
            state = tail_match.group("state").strip()
            postal = tail_match.group("postal").strip()
            parts = parts[:-1]

    # If still no city/state, try combining the last remaining part with possible state/zip in text
    if not state and not postal and parts:
        last_piece = parts[-1]
        tail_match = re.match(r"^(?P<city>.+?)\s*[,-]?\s+(?P<state>[A-Za-z]{2})\s+(?P<postal>\d{5}(?:-\d{4})?)$", last_piece)
        if tail_match:
            city = tail_match.group("city").strip()
            state = tail_match.group("state").strip()
            postal = tail_match.group("postal").strip()
            parts = parts[:-1]

    if not city and parts:
        city = parts[-1]
        parts = parts[:-1]

    if len(parts) >= 2:
        line2 = parts[1]
    if parts:
        line1 = parts[0]

    return {
        "text": cleaned_text,
        "line1": line1,
        "line2": line2,
        "city": city,
        "state": state,
        "postal_code": postal,
        "country": country,
    }


def _normalize_addresses(items):
    normalized = []
    if not items:
        return normalized
    for item in items:
        if isinstance(item, dict):
            raw_value = item.get("value") or item.get("address") or item.get("text") or ""
            if not raw_value and item.get("line"):
                raw_value = item.get("line")
            if raw_value:
                parsed = _parse_address_text(str(raw_value))
                normalized.append(
                    {
                        "label": item.get("label") or item.get("type") or "Address",
                        "value": raw_value,
                        **parsed,
                    }
                )
        elif isinstance(item, str):
            parsed = _parse_address_text(item)
            normalized.append({"label": "Address", "value": item, **parsed})
    return normalized


def sanitize_html_for_enrichment(html: str) -> str:
    """
    Strip only <style> blocks to reduce noise while keeping page content intact.
    """
    if not html:
        return ""
    return re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=re.IGNORECASE | re.DOTALL)


def build_supplier_prompt_bundle(html: str) -> dict:
    """Bundle the system+user prompt plus truncated HTML snippet for reuse."""
    sanitized_html = sanitize_html_for_enrichment(html)
    if len(sanitized_html) <= SUPPLIER_ENRICH_HTML_MAX_CHARS:
        html_snippet = sanitized_html
    else:
        html_snippet = f"{sanitized_html[:SUPPLIER_ENRICH_HTML_MAX_CHARS]}\n<!-- truncated -->"
    user_prompt = _build_supplier_enrich_prompt(html_snippet)
    return {
        "system": SUPPLIER_ENRICH_SYSTEM_PROMPT,
        "user": user_prompt,
        "html_snippet": html_snippet,
        "sanitized_html": sanitized_html,
    }


def _build_supplier_enrich_prompt(html: str) -> str:
    return (
        "After reviewing this company's website HTML, please produce the fields described earlier. "
        "Capture all logo URLs, as many addresses as possible (label each) but keep the full addresses together, every phone number and "
        "email, and the company's CAGE Code if available. Include any other public contact/social links "
        "in the social_links array. Respond ONLY in JSON.\n\n"
        f"HTML:\n{html}"
    )


def _extract_json_payload(text: str) -> dict:
    if not text:
        raise RuntimeError("OpenRouter returned an empty response.")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, count=1).strip()
        if "```" in cleaned:
            cleaned = cleaned.split("```", 1)[0].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        raise RuntimeError("OpenRouter response was not valid JSON.")


def _normalize_contact_rows(items, value_key="value", label_fallback="label", extra_value_keys=None):
    normalized = []
    if not items:
        return normalized
    extra_value_keys = extra_value_keys or []
    for item in items:
        if isinstance(item, dict):
            label = item.get("label") or item.get("type") or label_fallback.title()
            raw_value = item.get(value_key)
            if raw_value in (None, ""):
                for key in ["value", "address", "text"] + list(extra_value_keys):
                    if item.get(key):
                        raw_value = item.get(key)
                        break
            value = raw_value or ""
            if value:
                normalized.append({"label": label, value_key: value})
        elif isinstance(item, str):
            normalized.append({"label": label_fallback.title(), value_key: item})
    return normalized


def _normalize_ai_result(data: dict) -> dict:
    data = data or {}
    normalized = {
        "company_name": data.get("company_name"),
        "logo_url": data.get("logo_url"),
        "addresses": _normalize_addresses(data.get("addresses")),
        "phone_numbers": _normalize_contact_rows(
            data.get("phone_numbers"),
            value_key="value",
            label_fallback="Phone",
        ),
        "emails": _normalize_contact_rows(
            data.get("emails"),
            value_key="value",
            label_fallback="Email",
        ),
        "cage_code": data.get("cage_code"),
        "website_url": data.get("website_url"),
        "social_links": _normalize_contact_rows(data.get("social_links"), value_key="url", label_fallback="Link"),
        "notes": data.get("notes"),
    }
    return normalized


def call_openrouter_for_supplier(
    html: str, model_override: str | None = None, prompt_bundle: dict | None = None
) -> tuple[dict, str]:
    api_key = getattr(settings, "OPENROUTER_API_KEY", os.environ.get("OPENROUTER_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("OpenRouter API key is not configured.")
    base_url = getattr(settings, "OPENROUTER_BASE_URL", os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")).rstrip("/")
    model, _ = get_model_for_request(model_override)
    http_referer = getattr(settings, "OPENROUTER_HTTP_REFERER", os.environ.get("OPENROUTER_HTTP_REFERER", "")).strip()
    x_title = getattr(settings, "OPENROUTER_X_TITLE", os.environ.get("OPENROUTER_X_TITLE", "STATZCorp")).strip()
    fallback_models = getattr(settings, "OPENROUTER_MODEL_FALLBACKS", os.environ.get("OPENROUTER_MODEL_FALLBACKS", ""))

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if http_referer:
        headers["HTTP-Referer"] = http_referer
        headers["Referer"] = http_referer
    if x_title:
        headers["X-Title"] = x_title

    prompt_bundle = prompt_bundle or build_supplier_prompt_bundle(html)

    messages = [
        {"role": "system", "content": prompt_bundle["system"]},
        {"role": "user", "content": prompt_bundle["user"]},
    ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
    }
    if fallback_models:
        if isinstance(fallback_models, (list, tuple)):
            models_list = [m for m in fallback_models if m]
        else:
            models_list = [m.strip() for m in fallback_models.split(",") if m.strip()]
        if models_list:
            payload["models"] = models_list

    try:
        response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=(15, 120))
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter response did not include choices.")
    content = choices[0].get("message", {}).get("content") or ""
    parsed = _extract_json_payload(content)
    return _normalize_ai_result(parsed), model

def fetch_website_html(url: str, *, timeout: int = 10) -> str:
    """Return the raw HTML for the supplied URL using a basic GET request."""
    if not url or not url.strip():
        raise ValueError("A non-empty URL is required.")

    normalized_url = url.strip()
    parsed = urlparse(normalized_url)
    if not parsed.scheme:
        normalized_url = f"https://{normalized_url}"
        parsed = urlparse(normalized_url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are supported.")

    headers = {
        "User-Agent": "STATZCorpReportsBot/1.0 (+https://statzcorp.com)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        response = requests.get(normalized_url, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Unable to retrieve HTML from {normalized_url}: {exc}") from exc

    return response.text


def format_address_for_display(address) -> str:
    if not address:
        return ""
    parts = []
    for attr in ("address_line_1", "address_line_2", "city", "state", "postal_code", "zip", "country"):
        val = getattr(address, attr, None)
        if val:
            parts.append(str(val))
    if parts:
        return ", ".join(parts)
    return str(address)



class DashboardView(TemplateView):
    template_name = 'suppliers/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        suppliers_with_metrics = Supplier.objects.annotate(
            contract_count=Count('clin__contract', distinct=True),
            contract_value=Coalesce(
                Sum('clin__quote_value'),
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
                Q(supplier_type__code__iexact='P')
                | Q(supplier_type__description__icontains='packhouse')
            )

        manufacturer_qs = is_manufacturer(suppliers_with_metrics)
        distributor_qs = is_distributor(suppliers_with_metrics)
        packhouse_qs = is_packhouse(suppliers_with_metrics)
        unspecified_qs = suppliers_with_metrics.filter(supplier_type__isnull=True)
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

        contracts_qs = Contract.objects.filter(
            clin__supplier__isnull=False
        ).distinct()
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
        documents = list(
            SupplierDocument.objects.filter(supplier=supplier)
            .select_related('certification', 'classification')
            .order_by('-id')
        )
        context['documents'] = documents[:25]
        certifications = SupplierCertification.objects.filter(supplier=supplier).select_related('certification_type').order_by('-certification_date', '-id')
        classifications = SupplierClassification.objects.filter(supplier=supplier).select_related('classification_type').order_by('-classification_date', '-id')
        context['certifications'] = certifications
        context['classifications'] = classifications
        cert_doc_map = {}
        class_doc_map = {}
        for doc in documents:
            if doc.certification_id and doc.certification_id not in cert_doc_map:
                cert_doc_map[doc.certification_id] = doc
            if doc.classification_id and doc.classification_id not in class_doc_map:
                class_doc_map[doc.classification_id] = doc
        context['certification_rows'] = [
            {
                'id': cert.id,
                'type_id': cert.certification_type_id,
                'type_name': cert.certification_type.name,
                'date': cert.certification_date,
                'expires': cert.certification_expiration,
                'compliance_status': cert.compliance_status,
                'document': cert_doc_map.get(cert.id),
            }
            for cert in certifications
        ]
        context['classification_rows'] = [
            {
                'id': classification.id,
                'type_id': classification.classification_type_id,
                'type_name': classification.classification_type.name,
                'date': classification.classification_date,
                'expires': classification.classification_expiration,
                'document': class_doc_map.get(classification.id),
            }
            for classification in classifications
        ]
        context['certification_types'] = CertificationType.objects.all().order_by('name')
        context['classification_types'] = ClassificationType.objects.all().order_by('name')
        context['today'] = timezone.localdate()
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

        clin_contract_ids = Clin.objects.filter(
            supplier=supplier,
            contract_id__isnull=False,
        ).values_list('contract_id', flat=True).distinct()
        contracts_qs = Contract.objects.filter(id__in=clin_contract_ids)
        clins_qs = Clin.objects.filter(supplier=supplier)

        context['contracts'] = (
            contracts_qs.select_related('status', 'company')
            .annotate(
                performance_flag=Case(
                    When(due_date_late=True, then=Value('Late')),
                    default=Value(''),
                    output_field=models.CharField(),
                )
            )
            .order_by('-award_date', '-created_on')
            .distinct()
        )

        context['contract_company_summary'] = (
            clins_qs.filter(contract_id__isnull=False)
            .values('contract__company__name')
            .annotate(
                contract_count=Count('contract_id', distinct=True),
                total_value=Coalesce(Sum('quote_value'), 0.0, output_field=models.FloatField()),
            )
            .order_by('contract__company__name')
        )

        context['clin_summary'] = clins_qs.aggregate(
            total_clins=Count('id'),
            total_value=Coalesce(Sum('quote_value'), 0.0, output_field=models.FloatField()),
        )
        return context


class SupplierEnrichView(LoginRequiredMixin, View):
    """
    GET: fetch the supplier website's raw HTML and return it as JSON.
    Does NOT modify the database.
    """

    def get(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)

        if not supplier.website_url:
            return JsonResponse({"error": "No website URL set for this supplier."}, status=400)

        try:
            html = fetch_website_html(supplier.website_url)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except RuntimeError as exc:
            return JsonResponse({"error": str(exc)}, status=502)

        prompt_bundle = build_supplier_prompt_bundle(html)
        sanitized_html = prompt_bundle.get("sanitized_html", html)
        context_prompt = {
            "system": prompt_bundle["system"],
            "user": prompt_bundle["user"],
            "combined": (
                f"System Message:\n{prompt_bundle['system']}\n\n"
                f"User Message:\n{prompt_bundle['user']}"
            ),
        }

        requested_model = (request.GET.get("model") or "").strip()
        model_info = get_openrouter_model_info()

        ai_result = None
        ai_error = None
        manual_only = str(request.GET.get("manual_only", "")).lower() in {"1", "true", "yes", "on"}
        model_used = requested_model or model_info["effective_model"]
        if not manual_only:
            try:
                ai_result, model_used = call_openrouter_for_supplier(
                    sanitized_html, model_override=requested_model or None, prompt_bundle=prompt_bundle
                )
                if ai_result and ai_result.get("logo_url"):
                    supplier.logo_url = ai_result.get("logo_url")
                    supplier.last_enriched_at = timezone.now()
                    if hasattr(supplier, "modified_by"):
                        supplier.modified_by = request.user
                    supplier.save(update_fields=["logo_url", "last_enriched_at", "modified_on", "modified_by"])
            except RuntimeError as exc:
                ai_error = str(exc)

        return JsonResponse(
            {
                "html": sanitized_html,
                "url": supplier.website_url,
                "ai_result": ai_result,
                "ai_error": ai_error,
                "model_used": model_used,
                "global_model_info": model_info,
                "context_prompt": context_prompt,
                "manual_only": manual_only,
            }
        )


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

        field = (data.get("field") or "").strip()
        value = data.get("value")

        allowed_fields = [
            "logo_url",
            "primary_phone",
            "business_phone",
            "business_fax",
            "primary_email",
            "business_email",
            "website_url",
            "cage_code",
        ]

        if field == "address":
            if not isinstance(value, dict):
                return JsonResponse({"error": "Invalid address payload."}, status=400)
            address_text = (value.get("text") or "").strip()
            selected_types = value.get("types") or []
            if not address_text or not isinstance(selected_types, (list, tuple)):
                return JsonResponse({"error": "Address text and types are required."}, status=400)
            line1 = value.get("line1") or address_text
            line2 = value.get("line2") or ""
            city = value.get("city") or ""
            state = value.get("state") or ""
            postal_code = value.get("postal_code") or ""
            country = value.get("country") or ""
            address_type_map = {
                "shipping": "shipping_address",
                "billing": "billing_address",
                "physical": "physical_address",
            }
            normalized_types = []
            for item in selected_types:
                key = str(item).lower()
                if key in address_type_map:
                    normalized_types.append(key)
            if not normalized_types:
                return JsonResponse({"error": "Select at least one valid address type."}, status=400)
            address_obj = Address.objects.create(
                address_line_1=line1,
                address_line_2=line2 or country,
                city=city,
                state=state,
                zip=postal_code,
            )
            update_fields = []
            for addr_type in normalized_types:
                attr = address_type_map[addr_type]
                setattr(supplier, attr, address_obj)
                update_fields.append(attr)
        else:
            if field not in allowed_fields:
                return JsonResponse({"error": "Field not allowed"}, status=400)
            setattr(supplier, field, value)
            update_fields = [field]

        supplier.last_enriched_at = timezone.now()
        if hasattr(supplier, "modified_by"):
            supplier.modified_by = request.user
            update_fields.append("modified_by")
        update_fields.append("last_enriched_at")
        update_fields.append("modified_on")
        supplier.save(update_fields=update_fields)

        return JsonResponse({"ok": True})


class GlobalAIModelConfigView(LoginRequiredMixin, View):
    """Manage the shared OpenRouter model configuration."""

    def get(self, request):
        return JsonResponse(get_openrouter_model_info())

    def post(self, request):
        if not request.user.is_superuser:
            return JsonResponse({"error": "Not authorized"}, status=403)
        try:
            payload = json.loads(request.body or "{}")
        except ValueError:
            return JsonResponse({"error": "Invalid JSON payload"}, status=400)

        model_value = payload.get("model")
        needs_update = payload.get("needs_update")
        if isinstance(needs_update, str):
            needs_update = needs_update.lower() in {"1", "true", "yes", "on"}
        if model_value is None and needs_update is None:
            return JsonResponse({"error": "Provide a model or needs_update flag to change."}, status=400)

        info = save_openrouter_model_config(
            model_name=model_value,
            needs_update=needs_update,
            user=request.user,
        )
        status = "Shared model updated." if info["has_stored_model"] else "Shared model cleared."
        if info["needs_update"]:
            status += " Model is flagged for replacement."
        return JsonResponse({"ok": True, "info": info, "message": status})


class SupplierEnrichPageView(LoginRequiredMixin, TemplateView):
    template_name = 'suppliers/supplier_enrich.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        supplier = get_object_or_404(Supplier, pk=kwargs.get("pk"))
        context['supplier'] = supplier
        model_info = get_openrouter_model_info()
        context['default_ai_model'] = model_info["stored_model"] or model_info["effective_model"]
        context['global_ai_model_info'] = model_info
        context['global_ai_model_info_json'] = json.dumps(model_info)
        snapshot = {
            "primary_phone": supplier.primary_phone or "",
            "business_phone": supplier.business_phone or "",
            "business_fax": supplier.business_fax or "",
            "primary_email": supplier.primary_email or "",
            "business_email": supplier.business_email or "",
            "cage_code": supplier.cage_code or "",
            "addresses": {
                "physical": format_address_for_display(supplier.physical_address),
                "shipping": format_address_for_display(supplier.shipping_address),
                "billing": format_address_for_display(supplier.billing_address),
            },
        }
        context['supplier_snapshot_json'] = json.dumps(snapshot)
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


class SuppliersInfoByType(LoginRequiredMixin, ListView):
    template_name = 'suppliers/suppliers_by_type.html'
    model = Supplier
    context_object_name = 'suppliers'
    paginate_by = 2

    def get_queryset(self):
        qs = super().get_queryset()
        # store slug on self so we can reuse it in get_context_data
        self.type_slug = self.kwargs.get('type_slug', '').lower()

        if self.type_slug == 'unspecified':
            return qs.filter(supplier_type__isnull=True)

        return qs.filter(supplier_type__description__iexact=self.type_slug)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        slug = getattr(self, 'type_slug', '').lower()

        label_map = {
            'manufacturer': 'Manufacturer',
            'distributor': 'Distributor',
            'packhouse': 'PackHouse',
            'other': 'Other',
            'unspecified': 'Unspecified',
        }

        context['type_label'] = label_map.get(slug, 'Suppliers')
        return context
