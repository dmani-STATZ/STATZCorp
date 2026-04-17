"""
Read-only diagnostics: list SharePoint site, drive, and list IDs via Microsoft Graph (GCC High).
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from users.sharepoint_services import GRAPH_BASE, get_graph_service_token


class Command(BaseCommand):
    help = (
        "Discover SharePoint site, document library, and list IDs using the "
        "GRAPH_MAIL_* service principal (no database writes)."
    )

    def handle(self, *args, **options):
        tenant = (getattr(settings, "GRAPH_MAIL_TENANT_ID", None) or "").strip()
        client_id = (getattr(settings, "GRAPH_MAIL_CLIENT_ID", None) or "").strip()
        secret = (getattr(settings, "GRAPH_MAIL_CLIENT_SECRET", None) or "").strip()
        if not tenant or not client_id or not secret:
            self.stdout.write(
                self.style.ERROR(
                    "Missing GRAPH_MAIL_TENANT_ID, GRAPH_MAIL_CLIENT_ID, and/or "
                    "GRAPH_MAIL_CLIENT_SECRET in the environment or Django settings."
                )
            )
            sys.exit(1)

        try:
            token = get_graph_service_token()
        except RuntimeError as exc:
            self.stdout.write(self.style.ERROR(str(exc)))
            sys.exit(1)

        headers = {"Authorization": f"Bearer {token}"}
        site_id: Optional[str] = None
        drives: List[Dict[str, Any]] = []

        # 2) Sites search
        sites_url = f"{GRAPH_BASE}/sites?search=Statz"
        self.stdout.write(self.style.SUCCESS("Querying sites (search=Statz)..."))
        try:
            r = requests.get(sites_url, headers=headers, timeout=120)
            if r.status_code != 200:
                self.stdout.write(
                    self.style.WARNING(
                        f"Sites request failed HTTP {r.status_code}: {r.text}"
                    )
                )
            else:
                data = r.json()
                sites = data.get("value") or []
                if not sites:
                    self.stdout.write(
                        self.style.WARNING("No sites returned for search=Statz.")
                    )
                for s in sites:
                    sid = s.get("id", "")
                    dname = s.get("displayName", "")
                    web = s.get("webUrl", "")
                    self.stdout.write(f"  site id: {sid}")
                    self.stdout.write(f"  displayName: {dname}")
                    self.stdout.write(f"  webUrl: {web}")
                    self.stdout.write("")
                if sites:
                    site_id = sites[0].get("id")
        except requests.RequestException as exc:
            self.stdout.write(self.style.WARNING(f"Sites request error: {exc}"))

        # 3) Drives for first site
        if site_id:
            enc_site = quote(site_id, safe="")
            drives_url = f"{GRAPH_BASE}/sites/{enc_site}/drives"
            self.stdout.write(self.style.SUCCESS(f"Listing drives for site {site_id!r}..."))
            try:
                r = requests.get(drives_url, headers=headers, timeout=120)
                if r.status_code != 200:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Drives request failed HTTP {r.status_code}: {r.text}"
                        )
                    )
                else:
                    drives = r.json().get("value") or []
                    for d in drives:
                        self.stdout.write(
                            f"  drive id: {d.get('id')} | name: {d.get('name')} | "
                            f"driveType: {d.get('driveType')}"
                        )
                    self.stdout.write("")
            except requests.RequestException as exc:
                self.stdout.write(self.style.WARNING(f"Drives request error: {exc}"))

            # 4) Lists
            lists_url = f"{GRAPH_BASE}/sites/{enc_site}/lists"
            self.stdout.write(self.style.SUCCESS(f"Listing lists for site {site_id!r}..."))
            try:
                r = requests.get(lists_url, headers=headers, timeout=120)
                if r.status_code != 200:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Lists request failed HTTP {r.status_code}: {r.text}"
                        )
                    )
                else:
                    for lst in (r.json().get("value") or []):
                        tmpl = (lst.get("list") or {}).get("template")
                        self.stdout.write(
                            f"  list id: {lst.get('id')} | displayName: {lst.get('displayName')} | "
                            f"template: {tmpl}"
                        )
                    self.stdout.write("")
            except requests.RequestException as exc:
                self.stdout.write(self.style.WARNING(f"Lists request error: {exc}"))

        # 5) Summary
        self.stdout.write(self.style.SUCCESS("--- Summary (.env) ---"))
        if site_id:
            self.stdout.write(f"SHAREPOINT_SITE_ID = {site_id}")
        else:
            self.stdout.write(
                self.style.WARNING(
                    "SHAREPOINT_SITE_ID = (set manually after identifying the correct site above)"
                )
            )

        suggested_drive: Optional[str] = None
        for d in drives:
            name = (d.get("name") or "").strip()
            if name in ("Documents", "Shared Documents"):
                suggested_drive = d.get("id")
                break

        if suggested_drive:
            self.stdout.write(
                f'SHAREPOINT_DRIVE_ID = {suggested_drive}  # library named "Documents" or "Shared Documents"'
            )
        else:
            self.stdout.write(
                "SHAREPOINT_DRIVE_ID = (pick the drive id for Documents or Shared Documents from the list above)"
            )

        self.stdout.write(
            "SHAREPOINT_CALENDAR_LIST_ID = DCAD2BC3-8205-4533-8AC1-AC0EED519D2C  # known calendar list"
        )
        self.stdout.write(
            "(SHAREPOINT_CALENDAR_LIST_ID is already the project default if unset in .env.)"
        )
