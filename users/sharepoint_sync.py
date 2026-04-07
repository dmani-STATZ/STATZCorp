"""
Two-way sync between WorkCalendarEvent and a SharePoint calendar list via Microsoft Graph.
GCC High: graph.microsoft.us, login.microsoftonline.us.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from users.models import WorkCalendarEvent

logger = logging.getLogger(__name__)
User = get_user_model()


def _graph_credentials() -> Tuple[str, str, str]:
    client_id = getattr(settings, "AZURE_CLIENT_ID", None) or settings.AZURE_AD_CONFIG.get(
        "app_id", ""
    )
    client_secret = getattr(settings, "AZURE_CLIENT_SECRET", None) or settings.AZURE_AD_CONFIG.get(
        "app_secret", ""
    )
    tenant_id = getattr(settings, "AZURE_TENANT_ID", None) or settings.AZURE_AD_CONFIG.get(
        "tenant_id", ""
    )
    if not (client_id and client_secret and tenant_id):
        raise ImproperlyConfigured(
            "AZURE_CLIENT_ID / AZURE_CLIENT_SECRET / AZURE_TENANT_ID (or AZURE_AD_CONFIG) "
            "must be set for SharePoint sync."
        )
    return client_id, client_secret, tenant_id


def _parse_graph_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = parse_datetime(str(value))
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone=timezone.utc)
    return dt


class SharePointCalendarSync:
    """Sync WorkCalendarEvent rows with a SharePoint calendar list."""

    def __init__(self) -> None:
        self._access_token: Optional[str] = None
        self._site_id: Optional[str] = None
        self._list_id: Optional[str] = None
        self.graph_base = getattr(
            settings, "GRAPH_BASE_URL", "https://graph.microsoft.us/v1.0"
        ).rstrip("/")
        self.sharepoint_site_url = getattr(
            settings, "SHAREPOINT_SITE_URL", "https://statzcorpgcch.sharepoint.us"
        ).rstrip("/")
        self.list_name = getattr(settings, "SHAREPOINT_LIST_NAME", "STATZ New Calendar")
        self.delete_local_if_removed = getattr(
            settings, "DELETE_LOCAL_IF_REMOVED_FROM_SP", False
        )
        _, _, self.tenant_id = _graph_credentials()

    def get_access_token(self) -> str:
        client_id, client_secret, tenant_id = _graph_credentials()
        token_url = f"https://login.microsoftonline.us/{tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.us/.default",
        }
        resp = requests.post(token_url, data=data, timeout=60)
        if resp.status_code != 200:
            logger.error("Graph token error: %s %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise ImproperlyConfigured("Graph token response missing access_token.")
        self._access_token = token
        return token

    def _headers(self) -> Dict[str, str]:
        token = self._access_token or self.get_access_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        _retry_auth: bool = True,
    ) -> Any:
        headers = self._headers()
        resp: Optional[requests.Response] = None
        for _attempt in range(8):
            resp = requests.request(
                method, url, headers=headers, params=params, json=json_body, timeout=120
            )
            if resp.status_code == 401 and _retry_auth:
                self._access_token = None
                headers = self._headers()
                _retry_auth = False
                continue
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "5"))
                time.sleep(min(wait, 60))
                continue
            if resp.status_code >= 400:
                logger.warning(
                    "Graph %s %s -> %s %s", method, url, resp.status_code, resp.text[:800]
                )
            resp.raise_for_status()
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.json()
        raise RuntimeError("Microsoft Graph request failed after retries.")

    def _site_path_segment(self) -> str:
        parsed = urlparse(self.sharepoint_site_url)
        host = (parsed.hostname or "").lower()
        if not host:
            raise ImproperlyConfigured("SHAREPOINT_SITE_URL must include a hostname.")
        path = (parsed.path or "").strip("/")
        if path:
            return f"{host}:/{path}"
        return f"{host}:/"

    def get_sharepoint_site_id(self) -> str:
        if self._site_id:
            return self._site_id
        segment = self._site_path_segment()
        url = f"{self.graph_base}/sites/{quote(segment, safe=':/')}"
        data = self._request_json("GET", url)
        site_id = data.get("id")
        if not site_id:
            raise ImproperlyConfigured("Could not resolve SharePoint site id from Graph.")
        self._site_id = site_id
        return site_id

    def get_sharepoint_list_id(self) -> str:
        if self._list_id:
            return self._list_id
        site_id = self.get_sharepoint_site_id()
        url = f"{self.graph_base}/sites/{site_id}/lists"
        safe_name = self.list_name.replace("'", "''")
        params = {"$filter": f"displayName eq '{safe_name}'"}
        data = self._request_json("GET", url, params=params)
        items = data.get("value") or []
        if not items:
            raise ImproperlyConfigured(
                f"SharePoint list named {self.list_name!r} was not found on the site."
            )
        lid = items[0].get("id")
        if not lid:
            raise ImproperlyConfigured("List response missing id.")
        self._list_id = lid
        return lid

    def get_sharepoint_items(self) -> List[Dict[str, Any]]:
        site_id = self.get_sharepoint_site_id()
        list_id = self.get_sharepoint_list_id()
        url = f"{self.graph_base}/sites/{site_id}/lists/{list_id}/items"
        params = {
            "$expand": "fields",
            "$top": "200",
        }
        out: List[Dict[str, Any]] = []
        while url:
            data = self._request_json("GET", url, params=params if params else None)
            params = None
            for row in data.get("value") or []:
                fields = row.get("fields") or {}
                merged = {
                    "id": row.get("id"),
                    "lastModifiedDateTime": row.get("lastModifiedDateTime"),
                    "createdDateTime": row.get("createdDateTime"),
                    "fields": fields,
                }
                out.append(merged)
            url = data.get("@odata.nextLink")
        return out

    def map_sp_to_local(self, sp_item: Dict[str, Any]) -> Dict[str, Any]:
        fields = sp_item.get("fields") or {}
        title = (fields.get("Title") or fields.get("title") or "").strip() or "(no title)"
        start = _parse_graph_datetime(
            fields.get("EventDate") or fields.get("eventDate") or fields.get("StartDate")
        )
        end = _parse_graph_datetime(
            fields.get("EndDate") or fields.get("endDate") or fields.get("EndDateTime")
        )
        if start is None:
            start = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        if end is None or end <= start:
            end = start + timedelta(hours=1)
        description = (fields.get("Description") or fields.get("description") or "").strip()
        location = (fields.get("Location") or fields.get("location") or "").strip()
        all_day_raw = fields.get("fAllDayEvent")
        if all_day_raw is None:
            all_day_raw = fields.get("fAllDayEvent0")
        all_day = bool(all_day_raw) if all_day_raw is not None else False
        django_ev_id = fields.get("DjangoEventId") or fields.get("djangoEventId") or ""
        return {
            "title": title,
            "start_at": start,
            "end_at": end,
            "description": description,
            "location": location,
            "all_day": all_day,
            "sharepoint_id": str(sp_item.get("id")) if sp_item.get("id") is not None else None,
            "django_event_id_hint": str(django_ev_id).strip() or None,
        }

    def map_local_to_sp(self, event: WorkCalendarEvent) -> Dict[str, Any]:
        meta = event.metadata if isinstance(event.metadata, dict) else {}
        all_day = bool(meta.get("all_day") or meta.get("sharepoint_all_day"))
        fields: Dict[str, Any] = {
            "Title": event.title,
            "EventDate": event.start_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "EndDate": event.end_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "Description": event.description or "",
            "Location": event.location or "",
            "fAllDayEvent": all_day,
            "DjangoEventId": str(event.pk),
        }
        return fields

    def _create_sp_item(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        site_id = self.get_sharepoint_site_id()
        list_id = self.get_sharepoint_list_id()
        url = f"{self.graph_base}/sites/{site_id}/lists/{list_id}/items"
        body = {"fields": fields}
        return self._request_json("POST", url, json_body=body)

    def _patch_sp_item(self, sp_item_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        site_id = self.get_sharepoint_site_id()
        list_id = self.get_sharepoint_list_id()
        url = (
            f"{self.graph_base}/sites/{site_id}/lists/{list_id}/items/{sp_item_id}/fields"
        )
        return self._request_json("PATCH", url, json_body=fields)

    def _sp_last_modified(self, sp_item: Dict[str, Any]) -> datetime:
        dt = _parse_graph_datetime(sp_item.get("lastModifiedDateTime"))
        if dt is None:
            return timezone.now()
        return dt

    def _resolve_sync_organizer(self) -> User:
        uid = getattr(settings, "SHAREPOINT_SYNC_ORGANIZER_USER_ID", None)
        if uid:
            return User.objects.get(pk=int(uid))
        u = User.objects.filter(is_superuser=True).order_by("pk").first()
        if u:
            return u
        u = User.objects.filter(is_staff=True).order_by("pk").first()
        if u:
            return u
        raise ImproperlyConfigured(
            "Set SHAREPOINT_SYNC_ORGANIZER_USER_ID or create a superuser for SharePoint-created events."
        )

    def run_sync(self) -> Dict[str, Any]:
        result = {
            "created_local": 0,
            "updated_local": 0,
            "created_sp": 0,
            "updated_sp": 0,
            "errors": [],
        }
        try:
            sp_items = self.get_sharepoint_items()
        except Exception as e:
            result["errors"].append(f"fetch_sharepoint_items: {e}")
            return result

        sp_by_id = {str(it["id"]): it for it in sp_items if it.get("id") is not None}

        organizer = self._resolve_sync_organizer()

        local_by_sp: Dict[str, WorkCalendarEvent] = {}
        for ev in WorkCalendarEvent.objects.exclude(sharepoint_id__isnull=True).exclude(
            sharepoint_id=""
        ):
            sid = str(ev.sharepoint_id)
            if sid in local_by_sp:
                result["errors"].append(f"duplicate sharepoint_id in DB: {sid}")
            else:
                local_by_sp[sid] = ev

        def apply_sp_to_local(sp_item: Dict[str, Any]) -> None:
            sp_id = str(sp_item.get("id"))
            mapped = self.map_sp_to_local(sp_item)
            sp_lm = self._sp_last_modified(sp_item)
            hint = mapped.pop("django_event_id_hint", None)
            all_day = mapped.pop("all_day")
            meta_key = "sharepoint_all_day"
            try:
                with transaction.atomic():
                    ev = None
                    if sp_id in local_by_sp:
                        ev = local_by_sp[sp_id]
                    elif hint:
                        cand = None
                        try:
                            pk = int(hint)
                            cand = WorkCalendarEvent.objects.filter(pk=pk).first()
                            if cand and cand.sharepoint_id and str(cand.sharepoint_id) != sp_id:
                                result["errors"].append(
                                    f"DjangoEventId {pk} linked to different SP id "
                                    f"({cand.sharepoint_id} vs {sp_id}); skipping hint match"
                                )
                                cand = None
                        except (TypeError, ValueError):
                            cand = None
                        ev = cand
                    if ev is None:
                        meta = {meta_key: all_day} if all_day else {}
                        ev = WorkCalendarEvent.objects.create(
                            title=mapped["title"],
                            description=mapped["description"],
                            start_at=mapped["start_at"],
                            end_at=mapped["end_at"],
                            location=mapped["location"],
                            organizer=organizer,
                            source_system="sharepoint",
                            sharepoint_id=sp_id,
                            sharepoint_last_modified=sp_lm,
                            metadata=meta,
                        )
                        result["created_local"] += 1
                        local_by_sp[sp_id] = ev
                        try:
                            self._patch_sp_item(sp_id, {"DjangoEventId": str(ev.pk)})
                        except Exception as pe:
                            result["errors"].append(f"patch DjangoEventId for new local {ev.pk}: {pe}")
                        return
                    prev_lm = ev.sharepoint_last_modified
                    if prev_lm is None or sp_lm > prev_lm:
                        meta = ev.metadata if isinstance(ev.metadata, dict) else {}
                        meta = {**meta, meta_key: all_day} if all_day else {**meta}
                        if not all_day:
                            meta.pop(meta_key, None)
                        WorkCalendarEvent.objects.filter(pk=ev.pk).update(
                            title=mapped["title"],
                            description=mapped["description"],
                            start_at=mapped["start_at"],
                            end_at=mapped["end_at"],
                            location=mapped["location"],
                            sharepoint_id=sp_id,
                            sharepoint_last_modified=sp_lm,
                            metadata=meta,
                        )
                        result["updated_local"] += 1
                        ev.refresh_from_db()
                        local_by_sp[sp_id] = ev
            except Exception as ex:
                result["errors"].append(f"sp_item {sp_id}: {ex}")

        for sp_item in sp_items:
            try:
                apply_sp_to_local(sp_item)
            except Exception as e:
                result["errors"].append(f"apply_sp_to_local outer {sp_item.get('id')}: {e}")

        local_by_sp = {
            str(ev.sharepoint_id): ev
            for ev in WorkCalendarEvent.objects.exclude(sharepoint_id__isnull=True).exclude(
                sharepoint_id=""
            )
        }

        for event in WorkCalendarEvent.objects.all().order_by("pk"):
            sp_id = (event.sharepoint_id or "").strip() or None
            try:
                if sp_id is None:
                    fields = self.map_local_to_sp(event)
                    created = self._create_sp_item(fields)
                    new_id = str(created.get("id", ""))
                    if not new_id:
                        result["errors"].append(f"create SP for event {event.pk}: no id in response")
                        continue
                    new_lm = _parse_graph_datetime(created.get("lastModifiedDateTime")) or timezone.now()
                    WorkCalendarEvent.objects.filter(pk=event.pk).update(
                        sharepoint_id=new_id,
                        sharepoint_last_modified=new_lm,
                    )
                    result["created_sp"] += 1
                    sp_by_id[new_id] = created
                    continue

                if sp_id not in sp_by_id:
                    if self.delete_local_if_removed:
                        event.delete()
                        continue
                    fields = self.map_local_to_sp(event)
                    created = self._create_sp_item(fields)
                    new_id = str(created.get("id", ""))
                    if not new_id:
                        result["errors"].append(
                            f"recreate SP for event {event.pk}: no id in response"
                        )
                        continue
                    new_lm = _parse_graph_datetime(created.get("lastModifiedDateTime")) or timezone.now()
                    WorkCalendarEvent.objects.filter(pk=event.pk).update(
                        sharepoint_id=new_id,
                        sharepoint_last_modified=new_lm,
                    )
                    result["created_sp"] += 1
                    sp_by_id[new_id] = created
                    continue

                sp_item = sp_by_id[sp_id]
                sp_lm = self._sp_last_modified(sp_item)
                ev_lm = event.sharepoint_last_modified
                if ev_lm is None:
                    WorkCalendarEvent.objects.filter(pk=event.pk).update(
                        sharepoint_last_modified=sp_lm
                    )
                    event.sharepoint_last_modified = sp_lm
                    ev_lm = sp_lm

                if sp_lm > ev_lm:
                    continue

                if event.updated_at > ev_lm and sp_lm <= ev_lm:
                    try:
                        self._patch_sp_item(sp_id, self.map_local_to_sp(event))
                        refreshed = self._request_json(
                            "GET",
                            f"{self.graph_base}/sites/{self.get_sharepoint_site_id()}/lists/"
                            f"{self.get_sharepoint_list_id()}/items/{sp_id}",
                            params={"$expand": "fields"},
                        )
                        new_lm = self._sp_last_modified(refreshed)
                        WorkCalendarEvent.objects.filter(pk=event.pk).update(
                            sharepoint_last_modified=new_lm
                        )
                        result["updated_sp"] += 1
                    except Exception as ue:
                        result["errors"].append(f"push event {event.pk} to SP: {ue}")
            except Exception as ex:
                result["errors"].append(f"local event {event.pk}: {ex}")

        return result
