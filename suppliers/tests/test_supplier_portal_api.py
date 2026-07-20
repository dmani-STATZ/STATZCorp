"""Tests for the supplier portal API (statzcorp-com → STATZWeb)."""

import json
import time
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from suppliers.models import (
    Contact,
    Supplier,
    SupplierContactCategory,
    SupplierPortalChangeLog,
)
from suppliers.portal.auth import build_canonical_string, sign_canonical


API_KEY = "test-portal-api-key"
HMAC_SECRET = "test-portal-hmac-secret"


@override_settings(
    SUPPLIER_PORTAL_API_KEY=API_KEY,
    SUPPLIER_PORTAL_HMAC_SECRET=HMAC_SECRET,
    SUPPLIER_PORTAL_NOTIFY_EMAIL="staff@example.com",
    SUPPLIER_PORTAL_RATE_LIMIT_PER_MIN=1000,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class SupplierPortalAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.supplier = Supplier.objects.create(
            name="Example Supplier LLC",
            cage_code="3WGD1",
            primary_email="owner@example-supplier.com",
            business_email="ap@example-supplier.com",
            business_phone="608-555-0100",
            archived=False,
        )
        self.archived = Supplier.objects.create(
            name="Archived Co",
            cage_code="ARCH01",
            primary_email="gone@example.com",
            archived=True,
        )
        self.category, _ = SupplierContactCategory.objects.get_or_create(
            name="Sales",
            defaults={"is_active": True, "sort_order": 2},
        )
        self.inactive_cat, _ = SupplierContactCategory.objects.get_or_create(
            name="InternalOnly",
            defaults={"is_active": False, "sort_order": 99},
        )
        if self.inactive_cat.is_active:
            self.inactive_cat.is_active = False
            self.inactive_cat.save(update_fields=["is_active"])

    def _sign(self, method, path, body=b"", timestamp=None):
        if timestamp is None:
            timestamp = str(int(time.time()))
        if isinstance(body, str):
            body = body.encode("utf-8")
        canonical = build_canonical_string(method, path, timestamp, body)
        signature = sign_canonical(HMAC_SECRET, canonical)
        return {
            "HTTP_X_API_KEY": API_KEY,
            "HTTP_X_TIMESTAMP": timestamp,
            "HTTP_X_SIGNATURE": signature,
        }

    def _get(self, path, **extra):
        headers = self._sign("GET", path, b"")
        headers.update(extra)
        return self.client.get(path, **headers)

    def _json(self, method, path, payload, **extra):
        body = json.dumps(payload)
        headers = self._sign(method, path, body.encode("utf-8"))
        headers["content_type"] = "application/json"
        headers.update(extra)
        return getattr(self.client, method.lower())(path, data=body, **headers)

    def test_missing_api_key_401(self):
        path = reverse("supplier_portal:verify", kwargs={"cage_code": "3WGD1"})
        ts = str(int(time.time()))
        sig = sign_canonical(
            HMAC_SECRET, build_canonical_string("GET", path, ts, b"")
        )
        resp = self.client.get(
            path,
            HTTP_X_TIMESTAMP=ts,
            HTTP_X_SIGNATURE=sig,
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "unauthorized")

    def test_bad_signature_401(self):
        path = reverse("supplier_portal:verify", kwargs={"cage_code": "3WGD1"})
        ts = str(int(time.time()))
        resp = self.client.get(
            path,
            HTTP_X_API_KEY=API_KEY,
            HTTP_X_TIMESTAMP=ts,
            HTTP_X_SIGNATURE="0" * 64,
        )
        self.assertEqual(resp.status_code, 401)

    def test_stale_timestamp_401(self):
        path = reverse("supplier_portal:verify", kwargs={"cage_code": "3WGD1"})
        stale = str(int(time.time()) - 600)
        headers = self._sign("GET", path, b"", timestamp=stale)
        resp = self.client.get(path, **headers)
        self.assertEqual(resp.status_code, 401)

    def test_archived_supplier_404(self):
        path = reverse("supplier_portal:verify", kwargs={"cage_code": "ARCH01"})
        resp = self._get(path)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "not_found")

    def test_verify_uses_primary_email(self):
        path = reverse("supplier_portal:verify", kwargs={"cage_code": "3WGD1"})
        resp = self._get(path)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["contact_email"], "owner@example-supplier.com")
        self.assertTrue(data["is_active"])
        self.assertEqual(data["cage_code"], "3WGD1")

    def test_profile_omits_excluded_fields(self):
        path = reverse("supplier_portal:profile", kwargs={"cage_code": "3WGD1"})
        resp = self._get(path)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for banned in (
            "probation",
            "notes",
            "cage_code_editable",
            "dodaac",
            "special_terms",
            "archived",
        ):
            self.assertNotIn(banned, data)
        self.assertIn("addresses", data)
        self.assertIn("billing", data["addresses"])
        if data["addresses"]["billing"] is not None:
            self.assertNotIn("country", data["addresses"]["billing"])

    def test_patch_rejects_excluded_field(self):
        path = reverse("supplier_portal:profile", kwargs={"cage_code": "3WGD1"})
        resp = self._json("PATCH", path, {"name": "Hacker LLC"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "forbidden")
        self.assertIn("name", resp.json()["error"]["fields"])

    def test_patch_profile_and_changelog(self):
        path = reverse("supplier_portal:profile", kwargs={"cage_code": "3WGD1"})
        with patch("suppliers.portal.views.notify_staff_of_change") as notify:
            resp = self._json(
                "PATCH",
                path,
                {"business_phone": "608-555-9999"},
            )
            self.assertEqual(resp.status_code, 200)
            notify.assert_called_once()
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.business_phone, "608-555-9999")
        log = SupplierPortalChangeLog.objects.get(action="patch_profile")
        self.assertEqual(log.cage_code, "3WGD1")
        self.assertIn("business_phone", log.changes)

    def test_contact_crud(self):
        create_path = reverse(
            "supplier_portal:contacts", kwargs={"cage_code": "3WGD1"}
        )
        resp = self._json(
            "POST",
            create_path,
            {
                "name": "Jane Doe",
                "email": "jane@example-supplier.com",
                "categories": ["Sales"],
            },
        )
        self.assertEqual(resp.status_code, 201)
        contact_id = resp.json()["id"]
        self.assertEqual(resp.json()["categories"], ["Sales"])

        detail = reverse(
            "supplier_portal:contact_detail",
            kwargs={"cage_code": "3WGD1", "contact_id": contact_id},
        )
        resp = self._json("PATCH", detail, {"title": "AP Manager"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["title"], "AP Manager")

        # Inactive category rejected
        resp = self._json(
            "PATCH", detail, {"categories": ["InternalOnly"]}
        )
        self.assertEqual(resp.status_code, 422)

        resp = self._json("DELETE", detail, {})
        # DELETE with empty JSON body — sign empty object
        # Actually _json sends {}. For DELETE our view ignores body.
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Contact.objects.filter(pk=contact_id).exists())
        self.assertTrue(
            SupplierPortalChangeLog.objects.filter(action="delete_contact").exists()
        )

    def test_document_upload_and_download(self):
        upload_path = reverse(
            "supplier_portal:documents", kwargs={"cage_code": "3WGD1"}
        )
        # Multipart signs empty body
        headers = self._sign("POST", upload_path, b"")
        upload = SimpleUploadedFile(
            "cert.pdf",
            b"%PDF-1.4 fake",
            content_type="application/pdf",
        )
        resp = self.client.post(
            upload_path,
            data={
                "file": upload,
                "doc_type": "CERT",
                "description": "ISO cert",
            },
            **headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        doc_id = resp.json()["id"]
        self.assertEqual(resp.json()["doc_type"], "CERT")
        self.assertTrue(
            SupplierPortalChangeLog.objects.filter(action="upload_document").exists()
        )

        dl_path = reverse(
            "supplier_portal:document_download",
            kwargs={"cage_code": "3WGD1", "document_id": doc_id},
        )
        resp = self._get(dl_path)
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("url", payload)
        self.assertIn("expires_at", payload)

        # Fetch signed file URL (no API key)
        file_resp = self.client.get(payload["url"])
        self.assertEqual(file_resp.status_code, 200)

    def test_unknown_cage_404(self):
        path = reverse("supplier_portal:verify", kwargs={"cage_code": "NOPE0"})
        resp = self._get(path)
        self.assertEqual(resp.status_code, 404)
