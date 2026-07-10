"""
Competitor Supplier Intelligence — fetch + parse DIBBS award PDFs for
watched competitor CAGEs (drafts-free; no DraftContract / SharePoint).

Stores LLM-derived role-tagged CAGE/DoDAAC entities per award, with
parse bookkeeping on CompetitorAwardParseStatus.

Reuses intake URL building + ``_extract_pdf_texts`` (text only — never
``parse_award_pdf``, which would burn Claude on CLIN/CMMC for intake).
Download via ``sales.services.dibbs_session.make_dibbs2_session``.

Inter-award pacing is intentionally slower than dibbs_awards_scraper.PAGE_DELAY
(2.0s) so multi-Claude bursts per award do not trip Anthropic 429s.
"""
from __future__ import annotations

import json
import logging
import re
import time
from decimal import Decimal
from io import BytesIO
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from sales.models import (
    CompanyCAGE,
    CompetitorAwardEntity,
    CompetitorAwardParseStatus,
    CompetitorWatchlist,
    DibbsAward,
)
from sales.services.dibbs_session import make_dibbs2_session

logger = logging.getLogger("sales.competitor_supplier_intel")

# Inter-award delay (full fetch + Claude cycle), not just DIBBS download pacing.
DEFAULT_REQUEST_DELAY_SECONDS = 5.0
DEFAULT_BATCH_SIZE = 15
DEFAULT_MAX_DURATION_SECONDS = 1800.0
MAX_ATTEMPTS = 3
_DIBBS2_DOWNLOAD_TIMEOUT = 60

# Haiku for structured entity classification (cheaper than Sonnet used by
# intake CLIN/IDIQ/CMMC extractors — see core/anthropic_client.MODEL_PRICING).
_ENTITY_LLM_MODEL = "claude-haiku-4-5-20251001"
_ENTITY_LLM_MAX_DOC_CHARS = 40_000
_SOURCE_NOTE_MAX_WORDS = 10

_VALID_CODE_TYPES = {
    CompetitorAwardEntity.CODE_TYPE_CAGE,
    CompetitorAwardEntity.CODE_TYPE_DODAAC,
    CompetitorAwardEntity.CODE_TYPE_UNKNOWN,
}
_VALID_ROLES = {choice[0] for choice in CompetitorAwardEntity.ROLE_CHOICES}
_CAGE_LIKE = re.compile(r"^[A-Z0-9]{5}$")


def _blank(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_code(value: Any) -> str:
    return _blank(value).upper()


def _cap_source_note(value: Any, max_words: int = _SOURCE_NOTE_MAX_WORDS) -> str:
    """Truncate source_note to at most max_words (defensive vs LLM overshoot)."""
    note = _blank(value)
    if not note:
        return ""
    words = note.split()
    if len(words) <= max_words:
        return note
    return " ".join(words[:max_words])


def get_pending_awards(limit: int) -> list[DibbsAward]:
    """
    Watched-competitor awards that still need entity intel (or failed
    under the attempt cap). Materializes the watchlist first (no-MARS).

    Excludes STATZ company CAGEs (``CompanyCAGE`` / ``dibbs_company_cage``)
    even if one was somehow added to the watchlist.

    Excludes terminal ``unavailable`` (e.g. live 404) so they are never
    retried.
    """
    cages = list(
        CompetitorWatchlist.objects.values_list("cage_code", flat=True)
    )
    if not cages:
        return []

    our_cages = list(
        CompanyCAGE.objects.filter(is_active=True).values_list(
            "cage_code", flat=True
        )
    )

    terminal_statuses = (
        CompetitorAwardParseStatus.STATUS_SUCCESS,
        CompetitorAwardParseStatus.STATUS_UNAVAILABLE,
    )

    qs = (
        DibbsAward.objects.filter(
            awardee_cage__in=cages,
            is_faux=False,
        )
        .exclude(awardee_cage__in=our_cages)
        .filter(
            Q(entity_parse_status__isnull=True)
            | (
                ~Q(entity_parse_status__parse_status__in=terminal_statuses)
                & Q(entity_parse_status__attempt_count__lt=MAX_ATTEMPTS)
            )
        )
        .order_by("award_date", "id")[:limit]
    )
    return list(qs)


def _extract_award_entities_via_claude_api(
    document_text: str,
) -> list[dict[str, str]]:
    """
    Broad LLM pass: identify every CAGE/DoDAAC-shaped code in the document.

    Uses Haiku (structured classification). Returns [] on any failure
    (never raises).

    Role policy for approved-sources / QPL / alternates lists: use
    ``role=OTHER`` (not MANUFACTURER). Only the specific source that appears
    to be the actual manufacturer for this award's delivery gets
    MANUFACTURER — list membership alone is not enough. This keeps ranking
    actionable; ``source_note`` still records list context.
    """
    if not document_text or not document_text.strip():
        return []

    text = document_text.strip()
    if len(text) > _ENTITY_LLM_MAX_DOC_CHARS:
        text = text[:_ENTITY_LLM_MAX_DOC_CHARS]

    try:
        from core.anthropic_client import call_anthropic

        prompt = f"""You are extracting every CAGE code and DoDAAC from a US Government DD Form 1155 award document.

A CAGE code and a DoDAAC are both 5-character alphanumeric tokens (letters and digits). Do NOT confuse them:
- CAGE: contractor / manufacturer / OEM / packaging facility identifiers (often labeled CAGE, CODE, MFR. CAGE, or embedded in reference-drawing notes).
- DoDAAC: government office identifiers (buyer office, payment office, ship-to, etc.) — same shape as a CAGE but they are NOT suppliers.

Identify EVERY distinct 5-character alphanumeric code that looks like a CAGE or DoDAAC. For each, classify:
- "code": the 5-character code uppercased
- "code_type": one of "CAGE", "DODAAC", "UNKNOWN"
- "role": one of "CONTRACTOR", "OEM_DESIGN_AUTHORITY", "MANUFACTURER", "BUYER", "PAYMENT_OFFICE", "PACKAGING", "OTHER"
  - CONTRACTOR = prime contractor / Block 9 awardee
  - OEM_DESIGN_AUTHORITY = design authority / OEM called out separately from the manufacturer
  - MANUFACTURER = ONLY the specific, actual manufacturer or source for THIS award's delivery (e.g. PLACE OF INSPECTION for SUPPLIES, a single named MFR, or an explicit "manufacture at" / "source" callout). Do NOT use MANUFACTURER for every entry on an approved-sources, QPL, qualified-products, or alternates list.
  - BUYER = buying office / contracting office DoDAAC
  - PAYMENT_OFFICE = payment / finance office DoDAAC
  - PACKAGING = packaging / packhouse inspection party
  - OTHER = none of the above, OR a code that appears only as one of several approved/alternate/QPL sources (list membership without confirmation it was the source used for this award)
- "entity_name": the printed organization name next to the code if present, else null
- "source_note": REQUIRED. At most 10 words. Concretely where the code was found and how it was used. Examples:
  - "Block 9, listed as prime contractor"
  - "Section C, one of 14 approved alternates"
  - "PLACE OF INSPECTION for SUPPLIES"
  - "handwritten remark near CLIN 0002 delivery"
  Never leave source_note empty. Prefer location + role context over vague phrases.

Return ONLY a JSON array. No markdown, no explanation, no code fences.
If none found, return [].

DOCUMENT TEXT:
{text}"""

        payload = {
            "model": _ENTITY_LLM_MODEL,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        }
        body = call_anthropic(
            payload, "sales.competitor_supplier_intel._extract_award_entities_via_claude_api"
        )

        raw_text = ""
        for block in body.get("content", []):
            if block.get("type") == "text":
                raw_text += block.get("text", "")

        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text)
            raw_text = re.sub(r"\n?```$", "", raw_text)

        result = json.loads(raw_text)
        if not isinstance(result, list):
            return []

        rows: list[dict[str, str]] = []
        for item in result:
            if not isinstance(item, dict):
                continue
            code = _normalize_code(item.get("code"))
            if not code or not _CAGE_LIKE.match(code):
                continue
            source_note = _cap_source_note(item.get("source_note"))
            if not source_note:
                continue
            code_type = _blank(item.get("code_type")).upper()
            if code_type not in _VALID_CODE_TYPES:
                code_type = CompetitorAwardEntity.CODE_TYPE_UNKNOWN
            role = _blank(item.get("role")).upper()
            if role not in _VALID_ROLES:
                role = CompetitorAwardEntity.ROLE_OTHER
            rows.append(
                {
                    "code": code,
                    "code_type": code_type,
                    "role": role,
                    "entity_name": _blank(item.get("entity_name"))[:255],
                    "source_note": source_note,
                    "extraction_method": CompetitorAwardEntity.METHOD_LLM,
                }
            )
        return rows

    except Exception as exc:
        logger.warning(
            "competitor_supplier_intel: LLM entity extraction failed: %s", exc
        )
        return []


def _persist_entities(award: DibbsAward, entity_dicts: list[dict[str, str]]) -> None:
    """Replace all entities for this award (retry-safe; no duplicates)."""
    CompetitorAwardEntity.objects.filter(award=award).delete()
    if not entity_dicts:
        return
    CompetitorAwardEntity.objects.bulk_create(
        [
            CompetitorAwardEntity(
                award=award,
                code=row["code"],
                code_type=row["code_type"],
                role=row["role"],
                entity_name=row["entity_name"],
                source_note=row["source_note"],
                extraction_method=row["extraction_method"],
            )
            for row in entity_dicts
        ]
    )


def fetch_and_parse_award(award: DibbsAward) -> dict:
    """
    Fetch the DD Form 1155 for one DibbsAward, extract text, run the LLM
    entity pass, and upsert CompetitorAwardParseStatus + CompetitorAwardEntity.
    Never raises. Does not call intake ``parse_award_pdf`` (no CLIN/CMMC spend).
    """
    result = {
        "ok": False,
        "parse_status": None,
        "error": None,
    }
    now = timezone.now()

    try:
        existing = CompetitorAwardParseStatus.objects.filter(award=award).first()
        prior_attempts = existing.attempt_count if existing else 0
    except Exception as exc:
        logger.exception(
            "competitor_supplier_intel: failed reading prior status for award %s: %s",
            award.pk,
            exc,
        )
        prior_attempts = 0

    # Retriable attempts only — unavailable (404 / aged-off) does not increment.
    defaults: dict[str, Any] = {
        "attempt_count": prior_attempts + 1,
        "last_attempted_at": now,
        "fetch_error": False,
    }

    def _persist_unavailable(notes: str) -> dict:
        """Terminal: document gone from DIBBS. Do not burn attempt_count."""
        unavailable_defaults = {
            "attempt_count": prior_attempts,
            "last_attempted_at": now,
            "parse_status": CompetitorAwardParseStatus.STATUS_UNAVAILABLE,
            "parse_notes": notes,
            "fetch_error": True,
        }
        try:
            with transaction.atomic():
                CompetitorAwardParseStatus.objects.update_or_create(
                    award=award, defaults=unavailable_defaults
                )
                CompetitorAwardEntity.objects.filter(award=award).delete()
        except Exception:
            logger.exception(
                "competitor_supplier_intel: failed to persist unavailable status "
                "for award %s",
                award.pk,
            )
        result["error"] = notes
        result["parse_status"] = CompetitorAwardParseStatus.STATUS_UNAVAILABLE
        return result

    try:
        # Lazy cross-app imports (sales → intake) per project convention.
        from intake.ingest import _build_dibbs_award_pdf_url
        from intake.pdf_parser import _extract_pdf_texts

        award_date = (
            award.award_date.isoformat()
            if hasattr(award.award_date, "isoformat")
            else str(award.award_date or "")
        )
        basic = (award.award_basic_number or "").strip().upper()
        do_num = (award.delivery_order_number or "").strip().upper()
        pdf_url = _build_dibbs_award_pdf_url(basic, do_num, award_date)

        if not pdf_url:
            defaults.update(
                {
                    "parse_status": CompetitorAwardParseStatus.STATUS_FAILED,
                    "parse_notes": (
                        "Cannot build DIBBS PDF URL "
                        f"(basic={basic!r}, do={do_num!r}, date={award_date!r})."
                    ),
                    "fetch_error": True,
                }
            )
            with transaction.atomic():
                CompetitorAwardParseStatus.objects.update_or_create(
                    award=award, defaults=defaults
                )
                CompetitorAwardEntity.objects.filter(award=award).delete()
            result["error"] = defaults["parse_notes"]
            result["parse_status"] = CompetitorAwardParseStatus.STATUS_FAILED
            return result

        session = make_dibbs2_session()
        response = session.get(pdf_url, timeout=_DIBBS2_DOWNLOAD_TIMEOUT)
        if response.status_code == 404:
            return _persist_unavailable(
                "DIBBS returned HTTP 404 — award PDF no longer available "
                f"(likely past ~45-day retention). url={pdf_url}"
            )
        response.raise_for_status()
        pdf_bytes = response.content
        if not pdf_bytes:
            raise ValueError("Empty response body from DIBBS.")
        content_type = response.headers.get("Content-Type", "")
        if "html" in content_type.lower():
            raise ValueError(
                "DIBBS returned an HTML page instead of a PDF. "
                "The DOD acknowledgement session may not have been established correctly."
            )

        pdf_file = BytesIO(pdf_bytes)
        pdf_file.name = f"{basic or award.notice_id}.pdf"
        full_text, _page_one = _extract_pdf_texts(pdf_file)

        if not full_text.strip():
            parse_status = CompetitorAwardParseStatus.STATUS_FAILED
            notes = "PDF text extraction returned empty."
            llm_rows: list[dict[str, str]] = []
        else:
            llm_rows = _extract_award_entities_via_claude_api(full_text)
            if llm_rows:
                parse_status = CompetitorAwardParseStatus.STATUS_SUCCESS
                notes = f"Extracted {len(llm_rows)} LLM entities."
            else:
                parse_status = CompetitorAwardParseStatus.STATUS_PARTIAL
                notes = "LLM entity pass returned no entities (or failed)."

        defaults.update(
            {
                "parse_status": parse_status,
                "parse_notes": notes,
                "fetch_error": False,
            }
        )

        with transaction.atomic():
            CompetitorAwardParseStatus.objects.update_or_create(
                award=award, defaults=defaults
            )
            _persist_entities(award, llm_rows)

        result["ok"] = parse_status == CompetitorAwardParseStatus.STATUS_SUCCESS
        result["parse_status"] = parse_status
        return result

    except Exception as exc:
        logger.exception(
            "competitor_supplier_intel: fetch/parse failed for award %s (%s): %s",
            award.pk,
            getattr(award, "notice_id", ""),
            exc,
        )
        defaults.update(
            {
                "parse_status": CompetitorAwardParseStatus.STATUS_FAILED,
                "parse_notes": f"Fetch/parse error: {exc}",
                "fetch_error": True,
            }
        )
        try:
            with transaction.atomic():
                CompetitorAwardParseStatus.objects.update_or_create(
                    award=award, defaults=defaults
                )
                CompetitorAwardEntity.objects.filter(award=award).delete()
        except Exception:
            logger.exception(
                "competitor_supplier_intel: failed to persist failure status for award %s",
                award.pk,
            )
        result["error"] = str(exc)
        result["parse_status"] = CompetitorAwardParseStatus.STATUS_FAILED
        return result


def _budget_available() -> bool:
    from core.models import APIBudget

    budget = APIBudget.get()
    return budget.balance_usd > Decimal("0")


def process_pending_competitor_extractions(
    batch_size: int = DEFAULT_BATCH_SIZE,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
    max_duration_seconds: float | None = DEFAULT_MAX_DURATION_SECONDS,
) -> dict:
    """
    Process pending watched-competitor award PDFs (new + historical backlog).

    Budget guard → get_pending_awards → fetch/parse with pacing and time-box.
    Invoked as the final phase of ``scrape_awards`` (and optionally the manual
    debug management command). When ``max_duration_seconds`` is set, stop
    starting new awards after the current one finishes once wall-clock
    elapsed time reaches the limit.
    """
    summary = {
        "processed": 0,
        "success": 0,
        "failure": 0,
        "skipped_budget": False,
        "pending_found": 0,
        "stopped_for_duration": False,
    }
    started_at = time.monotonic()

    if not _budget_available():
        logger.warning(
            "competitor_supplier_intel: APIBudget balance_usd <= 0; stopping run."
        )
        summary["skipped_budget"] = True
        return summary

    awards = get_pending_awards(batch_size)
    summary["pending_found"] = len(awards)
    if not awards:
        logger.info("competitor_supplier_intel: no pending awards.")
        return summary

    for index, award in enumerate(awards):
        if not _budget_available():
            logger.warning(
                "competitor_supplier_intel: APIBudget depleted mid-run after %d awards; stopping.",
                summary["processed"],
            )
            summary["skipped_budget"] = True
            break

        outcome = fetch_and_parse_award(award)
        summary["processed"] += 1
        if outcome.get("ok"):
            summary["success"] += 1
        else:
            summary["failure"] += 1

        if (
            max_duration_seconds is not None
            and max_duration_seconds > 0
            and (time.monotonic() - started_at) >= max_duration_seconds
        ):
            summary["stopped_for_duration"] = True
            logger.info(
                "competitor_supplier_intel: max_duration_seconds=%.0f reached after %d awards; stopping.",
                max_duration_seconds,
                summary["processed"],
            )
            break

        if index < len(awards) - 1 and request_delay_seconds > 0:
            time.sleep(request_delay_seconds)

    logger.info(
        "competitor_supplier_intel: done processed=%d success=%d failure=%d "
        "budget_stop=%s duration_stop=%s",
        summary["processed"],
        summary["success"],
        summary["failure"],
        summary["skipped_budget"],
        summary["stopped_for_duration"],
    )
    return summary
