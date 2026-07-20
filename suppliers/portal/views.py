"""Supplier portal API views (Phase 1 reads + Phase 2 writes)."""

import json
import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from contracts.models import Address
from suppliers.models import (
    Contact,
    Supplier,
    SupplierContactCategory,
    SupplierDocument,
)

from .audit import record_change
from .auth import authenticate_request
from .downloads import mint_download_url, verify_download_token
from .errors import (
    bad_request,
    conflict,
    forbidden,
    not_found,
    server_error,
    unauthorized,
    validation_error,
)
from .notify import notify_staff_of_change
from .serializers import (
    ADDRESS_API_TO_MODEL,
    ADDRESS_SLOT_TO_FK,
    ADDRESS_SLOTS,
    CONTACT_WRITABLE_FIELDS,
    PROFILE_SCALAR_FIELDS,
    address_snapshot,
    contact_snapshot,
    serialize_contact,
    serialize_document,
    serialize_profile,
    serialize_verify,
)
from .throttling import check_rate_limit

logger = logging.getLogger(__name__)


def get_active_supplier(cage_code):
    """Return non-archived supplier or None."""
    if not cage_code:
        return None
    return (
        Supplier.objects.filter(cage_code=cage_code, archived=False)
        .select_related(
            "billing_address",
            "shipping_address",
            "physical_address",
        )
        .first()
    )


def load_profile_supplier(cage_code):
    supplier = get_active_supplier(cage_code)
    if supplier is None:
        return None
    # Re-fetch with prefetches for profile payload
    return (
        Supplier.objects.filter(pk=supplier.pk)
        .select_related(
            "billing_address",
            "shipping_address",
            "physical_address",
        )
        .prefetch_related(
            "contacts__categories",
            "suppliercertification_set__certification_type",
            "supplierclassification_set__classification_type",
            "documents__certification__certification_type",
            "documents__classification__classification_type",
        )
        .first()
    )


def _parse_json_body(request):
    if not request.body:
        return {}, None
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, bad_request("Malformed JSON body.")
    if not isinstance(data, dict):
        return None, bad_request("JSON body must be an object.")
    return data, None


def _apply_address_slot(supplier, slot, value, changes):
    """Create/update/clear an address slot. Mutates supplier; fills changes dict."""
    fk_name = ADDRESS_SLOT_TO_FK[slot]
    old_addr = getattr(supplier, fk_name)
    old_snap = address_snapshot(old_addr)

    if value is None:
        setattr(supplier, fk_name, None)
        changes[f"addresses.{slot}"] = {"old": old_snap, "new": None}
        return

    if not isinstance(value, dict):
        raise ValueError(f"addresses.{slot} must be an object or null")

    unknown = set(value.keys()) - set(ADDRESS_API_TO_MODEL.keys())
    if unknown:
        raise KeyError(sorted(unknown))

    if old_addr is None:
        addr = Address()
    else:
        addr = old_addr

    for api_key, model_key in ADDRESS_API_TO_MODEL.items():
        if api_key in value:
            setattr(addr, model_key, value[api_key] or None)
    addr.save()
    setattr(supplier, fk_name, addr)
    changes[f"addresses.{slot}"] = {"old": old_snap, "new": address_snapshot(addr)}


def _resolve_categories(names):
    """Return list of active categories or raise ValueError with message."""
    if names is None:
        return []
    if not isinstance(names, list):
        raise ValueError("categories must be a list of category names")
    resolved = []
    missing = []
    for name in names:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("categories must be non-empty strings")
        cat = SupplierContactCategory.objects.filter(
            name=name.strip(), is_active=True
        ).first()
        if cat is None:
            missing.append(name)
        else:
            resolved.append(cat)
    if missing:
        raise ValueError(f"Unknown or inactive categories: {', '.join(missing)}")
    return resolved


@method_decorator(csrf_exempt, name="dispatch")
class PortalAPIView(View):
    """Base CBV with auth, rate limit, and CSRF exempt."""

    def dispatch(self, request, *args, **kwargs):
        auth_err = authenticate_request(request)
        if auth_err is not None:
            return auth_err
        rl_err = check_rate_limit(request)
        if rl_err is not None:
            return rl_err
        try:
            return super().dispatch(request, *args, **kwargs)
        except Exception:
            logger.exception("Supplier portal API error")
            return server_error()


class SupplierVerifyView(PortalAPIView):
    def get(self, request, cage_code):
        supplier = get_active_supplier(cage_code)
        if supplier is None:
            return not_found()
        return JsonResponse(serialize_verify(supplier))


class SupplierProfileView(PortalAPIView):
    def get(self, request, cage_code):
        supplier = load_profile_supplier(cage_code)
        if supplier is None:
            return not_found()
        return JsonResponse(serialize_profile(supplier))

    def patch(self, request, cage_code):
        supplier = load_profile_supplier(cage_code)
        if supplier is None:
            return not_found()

        data, err = _parse_json_body(request)
        if err is not None:
            return err
        if not data:
            return bad_request("Request body must include at least one field.")

        allowed_top = set(PROFILE_SCALAR_FIELDS) | {"addresses"}
        rejected = sorted(set(data.keys()) - allowed_top)
        if rejected:
            return forbidden(
                "One or more fields are not editable via the supplier portal.",
                fields={k: "not editable" for k in rejected},
            )

        changes = {}
        try:
            with transaction.atomic():
                for field in PROFILE_SCALAR_FIELDS:
                    if field not in data:
                        continue
                    old = getattr(supplier, field)
                    new = data[field]
                    if new == "":
                        new = None
                    if old != new:
                        setattr(supplier, field, new)
                        changes[field] = {"old": old, "new": new}

                if "addresses" in data:
                    addresses = data["addresses"]
                    if not isinstance(addresses, dict):
                        return bad_request("addresses must be an object.")
                    bad_slots = sorted(set(addresses.keys()) - set(ADDRESS_SLOTS))
                    if bad_slots:
                        return forbidden(
                            "Unknown address slots.",
                            fields={k: "not editable" for k in bad_slots},
                        )
                    for slot, value in addresses.items():
                        try:
                            _apply_address_slot(supplier, slot, value, changes)
                        except KeyError as exc:
                            keys = exc.args[0] if exc.args else []
                            return forbidden(
                                "Unknown address fields.",
                                fields={f"addresses.{slot}.{k}": "not editable" for k in keys},
                            )
                        except ValueError as exc:
                            return bad_request(str(exc))

                if changes:
                    supplier.save()
                    log = record_change(
                        supplier=supplier,
                        action="patch_profile",
                        entity_type="supplier",
                        entity_id=supplier.pk,
                        changes=changes,
                    )
                else:
                    log = None
        except ValidationError as exc:
            return validation_error(
                "Validation failed.",
                fields={k: "; ".join(v) if isinstance(v, list) else str(v) for k, v in exc.message_dict.items()}
                if hasattr(exc, "message_dict")
                else None,
            )

        if log is not None:
            notify_staff_of_change(log)

        supplier = load_profile_supplier(cage_code)
        return JsonResponse(serialize_profile(supplier))


class ContactCollectionView(PortalAPIView):
    def post(self, request, cage_code):
        supplier = get_active_supplier(cage_code)
        if supplier is None:
            return not_found()

        data, err = _parse_json_body(request)
        if err is not None:
            return err

        rejected = sorted(set(data.keys()) - set(CONTACT_WRITABLE_FIELDS))
        if rejected:
            return forbidden(
                "One or more fields are not editable via the supplier portal.",
                fields={k: "not editable" for k in rejected},
            )

        name = (data.get("name") or "").strip()
        if not name:
            return validation_error(
                "Contact name is required.",
                fields={"name": "This field is required."},
            )

        email = data.get("email") or None
        if email == "":
            email = None

        if email and Contact.objects.filter(supplier=supplier, email__iexact=email).exists():
            return conflict(
                "A contact with this email already exists for this supplier.",
                fields={"email": "duplicate"},
            )

        try:
            categories = _resolve_categories(data.get("categories") or [])
        except ValueError as exc:
            return validation_error(str(exc), fields={"categories": str(exc)})

        salutation = data.get("salutation") or ""
        with transaction.atomic():
            contact = Contact.objects.create(
                supplier=supplier,
                salutation=salutation,
                name=name,
                title=data.get("title") or None,
                phone=data.get("phone") or None,
                email=email,
            )
            if categories:
                contact.categories.set(categories)
            snap = contact_snapshot(contact)
            changes = {k: {"old": None, "new": v} for k, v in snap.items()}
            log = record_change(
                supplier=supplier,
                action="create_contact",
                entity_type="contact",
                entity_id=contact.pk,
                changes=changes,
            )

        notify_staff_of_change(log)
        contact = Contact.objects.prefetch_related("categories").get(pk=contact.pk)
        return JsonResponse(serialize_contact(contact), status=201)


class ContactDetailView(PortalAPIView):
    def _get_contact(self, supplier, contact_id):
        return (
            Contact.objects.filter(supplier=supplier, pk=contact_id)
            .prefetch_related("categories")
            .first()
        )

    def patch(self, request, cage_code, contact_id):
        supplier = get_active_supplier(cage_code)
        if supplier is None:
            return not_found()
        contact = self._get_contact(supplier, contact_id)
        if contact is None:
            return not_found("No contact found for this supplier.")

        data, err = _parse_json_body(request)
        if err is not None:
            return err
        if not data:
            return bad_request("Request body must include at least one field.")

        rejected = sorted(set(data.keys()) - set(CONTACT_WRITABLE_FIELDS))
        if rejected:
            return forbidden(
                "One or more fields are not editable via the supplier portal.",
                fields={k: "not editable" for k in rejected},
            )

        changes = {}
        try:
            with transaction.atomic():
                if "name" in data:
                    new_name = (data.get("name") or "").strip()
                    if not new_name:
                        return validation_error(
                            "Contact name cannot be empty.",
                            fields={"name": "This field is required."},
                        )
                    if contact.name != new_name:
                        changes["name"] = {"old": contact.name, "new": new_name}
                        contact.name = new_name

                for field in ("salutation", "title", "phone", "email"):
                    if field not in data:
                        continue
                    old = getattr(contact, field)
                    new = data[field]
                    if new == "":
                        new = None if field != "salutation" else ""
                    if old != new:
                        if field == "email" and new:
                            dup = (
                                Contact.objects.filter(
                                    supplier=supplier, email__iexact=new
                                )
                                .exclude(pk=contact.pk)
                                .exists()
                            )
                            if dup:
                                return conflict(
                                    "A contact with this email already exists for this supplier.",
                                    fields={"email": "duplicate"},
                                )
                        changes[field] = {"old": old, "new": new}
                        setattr(contact, field, new)

                if "categories" in data:
                    try:
                        categories = _resolve_categories(data.get("categories"))
                    except ValueError as exc:
                        return validation_error(
                            str(exc), fields={"categories": str(exc)}
                        )
                    old_names = sorted(c.name for c in contact.categories.all())
                    new_names = sorted(c.name for c in categories)
                    if old_names != new_names:
                        changes["categories"] = {"old": old_names, "new": new_names}
                        contact.categories.set(categories)

                if changes:
                    contact.save()
                    log = record_change(
                        supplier=supplier,
                        action="update_contact",
                        entity_type="contact",
                        entity_id=contact.pk,
                        changes=changes,
                    )
                else:
                    log = None
        except ValidationError as exc:
            return validation_error(str(exc))

        if log is not None:
            notify_staff_of_change(log)

        contact = self._get_contact(supplier, contact_id)
        return JsonResponse(serialize_contact(contact))

    def delete(self, request, cage_code, contact_id):
        supplier = get_active_supplier(cage_code)
        if supplier is None:
            return not_found()
        contact = self._get_contact(supplier, contact_id)
        if contact is None:
            return not_found("No contact found for this supplier.")

        snap = contact_snapshot(contact)
        changes = {k: {"old": v, "new": None} for k, v in snap.items()}
        contact_pk = contact.pk
        with transaction.atomic():
            contact.delete()
            log = record_change(
                supplier=supplier,
                action="delete_contact",
                entity_type="contact",
                entity_id=contact_pk,
                changes=changes,
            )
        notify_staff_of_change(log)
        return JsonResponse({"ok": True})


class DocumentDownloadView(PortalAPIView):
    def get(self, request, cage_code, document_id):
        supplier = get_active_supplier(cage_code)
        if supplier is None:
            return not_found()
        doc = SupplierDocument.objects.filter(
            supplier=supplier, pk=document_id
        ).first()
        if doc is None:
            return not_found("No document found for this supplier.")
        return JsonResponse(mint_download_url(request, cage_code, document_id))


class DocumentUploadView(PortalAPIView):
    def post(self, request, cage_code):
        supplier = get_active_supplier(cage_code)
        if supplier is None:
            return not_found()

        upload = request.FILES.get("file")
        if upload is None:
            return bad_request("Missing file.", fields={"file": "required"})

        doc_type = (request.POST.get("doc_type") or "GENERAL").strip().upper()
        valid_types = {c[0] for c in SupplierDocument.DOC_TYPE_CHOICES}
        if doc_type not in valid_types:
            return validation_error(
                "Invalid doc_type.",
                fields={"doc_type": f"Must be one of: {', '.join(sorted(valid_types))}"},
            )

        description = request.POST.get("description") or None
        cert_id = request.POST.get("certification_id") or request.POST.get(
            "linked_certification_id"
        )
        class_id = request.POST.get("classification_id") or request.POST.get(
            "linked_classification_id"
        )

        from suppliers.models import SupplierCertification, SupplierClassification

        certification = None
        classification = None
        if cert_id:
            try:
                certification = SupplierCertification.objects.get(
                    supplier=supplier, pk=int(cert_id)
                )
            except (ValueError, SupplierCertification.DoesNotExist):
                return validation_error(
                    "Invalid certification_id.",
                    fields={"certification_id": "not found"},
                )
        if class_id:
            try:
                classification = SupplierClassification.objects.get(
                    supplier=supplier, pk=int(class_id)
                )
            except (ValueError, SupplierClassification.DoesNotExist):
                return validation_error(
                    "Invalid classification_id.",
                    fields={"classification_id": "not found"},
                )

        with transaction.atomic():
            doc = SupplierDocument(
                supplier=supplier,
                doc_type=doc_type,
                description=description,
                certification=certification,
                classification=classification,
            )
            doc.file = upload
            doc.save()
            meta = serialize_document(doc)
            changes = {
                k: {"old": None, "new": v}
                for k, v in meta.items()
                if k != "id"
            }
            changes["file"] = {"old": None, "new": getattr(upload, "name", "upload")}
            log = record_change(
                supplier=supplier,
                action="upload_document",
                entity_type="document",
                entity_id=doc.pk,
                changes=changes,
            )

        notify_staff_of_change(log)
        doc = (
            SupplierDocument.objects.select_related(
                "certification__certification_type",
                "classification__classification_type",
            )
            .get(pk=doc.pk)
        )
        return JsonResponse(serialize_document(doc), status=201)


@method_decorator(csrf_exempt, name="dispatch")
class DocumentFileServeView(View):
    """
    Browser-facing short-lived download. Authenticated via signed query token,
    not API key (so the browser can fetch the URL returned by download/).
    """

    def get(self, request, cage_code, document_id):
        expires = request.GET.get("expires")
        token = request.GET.get("token")
        if not verify_download_token(cage_code, document_id, expires, token):
            return unauthorized("Invalid or expired download link.")

        supplier = get_active_supplier(cage_code)
        if supplier is None:
            return not_found()
        doc = SupplierDocument.objects.filter(
            supplier=supplier, pk=document_id
        ).first()
        if doc is None or not doc.file:
            return not_found("No document found for this supplier.")

        try:
            return FileResponse(
                doc.file.open("rb"),
                as_attachment=True,
                filename=doc.file.name.rsplit("/", 1)[-1],
            )
        except Exception:
            logger.exception("Failed to serve supplier document %s", document_id)
            return server_error("Unable to serve document.")
