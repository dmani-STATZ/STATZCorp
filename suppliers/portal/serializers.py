"""Serialize supplier portal payloads (allowlisted fields only)."""

from datetime import timezone as datetime_timezone

from django.utils import timezone


PROFILE_SCALAR_FIELDS = (
    "business_phone",
    "business_fax",
    "business_email",
    "website_url",
    "primary_phone",
    "primary_email",
)

ADDRESS_SLOTS = ("billing", "shipping", "physical")
ADDRESS_SLOT_TO_FK = {
    "billing": "billing_address",
    "shipping": "shipping_address",
    "physical": "physical_address",
}
ADDRESS_API_TO_MODEL = {
    "line1": "address_line_1",
    "line2": "address_line_2",
    "city": "city",
    "state": "state",
    "zip": "zip",
}
ADDRESS_MODEL_TO_API = {v: k for k, v in ADDRESS_API_TO_MODEL.items()}

CONTACT_WRITABLE_FIELDS = (
    "salutation",
    "name",
    "title",
    "phone",
    "email",
    "categories",
)


def _iso_date(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _iso_datetime(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value.astimezone(datetime_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def serialize_address(address):
    if address is None:
        return None
    return {
        "line1": address.address_line_1 or "",
        "line2": address.address_line_2 or "",
        "city": address.city or "",
        "state": address.state or "",
        "zip": address.zip or "",
    }


def serialize_contact(contact):
    categories = [c.name for c in contact.categories.all()]
    return {
        "id": contact.id,
        "salutation": contact.salutation or "",
        "name": contact.name or "",
        "title": contact.title or "",
        "phone": contact.phone or "",
        "email": contact.email or "",
        "categories": categories,
    }


def serialize_certification(cert):
    return {
        "type": cert.certification_type.name if cert.certification_type_id else None,
        "certification_date": _iso_date(cert.certification_date),
        "certification_expiration": _iso_date(cert.certification_expiration),
        "compliance_status": cert.compliance_status,
    }


def serialize_classification(cls_row):
    return {
        "type": (
            cls_row.classification_type.name
            if cls_row.classification_type_id
            else None
        ),
        "classification_date": _iso_date(cls_row.classification_date),
        "classification_expiration": _iso_date(cls_row.classification_expiration),
    }


def serialize_document(doc):
    linked = None
    if doc.certification_id and doc.certification and doc.certification.certification_type_id:
        linked = doc.certification.certification_type.name
    elif doc.classification_id and doc.classification and doc.classification.classification_type_id:
        linked = doc.classification.classification_type.name
    return {
        "id": doc.id,
        "doc_type": doc.doc_type,
        "description": doc.description or "",
        "linked_certification": linked,
        "uploaded_on": _iso_datetime(doc.created_on),
    }


def serialize_verify(supplier):
    return {
        "cage_code": supplier.cage_code,
        "name": supplier.name,
        "is_active": True,
        "contact_email": supplier.primary_email or None,
    }


def serialize_profile(supplier):
    contacts = [serialize_contact(c) for c in supplier.contacts.all()]
    certifications = [
        serialize_certification(c)
        for c in supplier.suppliercertification_set.all()
    ]
    classifications = [
        serialize_classification(c)
        for c in supplier.supplierclassification_set.all()
    ]
    documents = [
        serialize_document(d)
        for d in supplier.documents.all()
    ]
    return {
        "cage_code": supplier.cage_code,
        "name": supplier.name,
        "business_phone": supplier.business_phone,
        "business_fax": supplier.business_fax,
        "business_email": supplier.business_email,
        "website_url": supplier.website_url,
        "primary_phone": supplier.primary_phone,
        "primary_email": supplier.primary_email,
        "addresses": {
            "billing": serialize_address(supplier.billing_address),
            "shipping": serialize_address(supplier.shipping_address),
            "physical": serialize_address(supplier.physical_address),
        },
        "contacts": contacts,
        "certifications": certifications,
        "classifications": classifications,
        "documents": documents,
    }


def address_snapshot(address):
    return serialize_address(address)


def contact_snapshot(contact):
    data = serialize_contact(contact)
    data.pop("id", None)
    return data
