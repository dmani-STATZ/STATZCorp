"""
SAM.gov Entity Management API v3 — read-only CAGE code lookup.

Usage:
    from sales.services.sam_entity import lookup_cage, get_or_fetch_cage
    data = lookup_cage("1ABC5")
    # Returns a cleaned dict of useful fields, or {'found': False, 'cage_code': ...}
    # Raises django.core.exceptions.ImproperlyConfigured if SAM_API_KEY not set.
    # Raises requests.RequestException (with clear message) on network/API errors.

    record = get_or_fetch_cage("1ABC5")  # SAMEntityCache; 30-day TTL; optional force_refresh.
"""
import logging

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

SAM_ENTITY_URL = "https://api.sam.gov/entity-information/v3/entities"

# Codes from sbaBusinessTypeList → set-aside flag keys (SBA-certified programs)
_SBA_CODE_MAP = {
    "A5": "sdvosb",
    "QF": "sdvosb",   # VOSB (broader)
    "A6": "hubzone",
    "8W": "wosb",
    "8E": "edwosb",
    "27": "8a",
    "2X": "small_business",
    "23": "small_business",
}

# Codes from businessTypeList used as fallback (self-reported, but reliable indicators)
# Only include codes where self-report is a genuine proxy for the certification.
# "27" (Self Certified Small Disadvantaged Business) is NOT 8(a) — excluded intentionally.
_BIZ_TYPE_FALLBACK_MAP = {
    "A5": "sdvosb",   # Veteran-Owned Business
    "QF": "sdvosb",   # Service-Disabled Veteran-Owned Business
    "A6": "hubzone",  # HUBZone (self-reported in businessTypeList)
    "8W": "wosb",
    "8E": "edwosb",
}


def lookup_cage(cage_code: str) -> dict:
    """
    Call the SAM.gov Entity Management API v3 for a given CAGE code.

    Returns a cleaned dict with:
        found (bool), cage_code, legal_name, uei, registration_status,
        registration_expiry, address (dict), business_types (list),
        naics_codes (list), psc_codes (list),
        set_aside_flags (dict — sdvosb/hubzone/wosb/edwosb/8a/small_business),
        exclusion_status (bool), sam_url (str)

    If no entity found: {'found': False, 'cage_code': cage_code}
    Raises ImproperlyConfigured if SAM_API_KEY not set.
    Raises requests.RequestException with a clear message on failure.
    """
    api_key = (getattr(settings, "SAM_API_KEY", "") or "").strip()
    if not api_key:
        raise ImproperlyConfigured(
            "SAM_API_KEY is not configured. Add it to your settings to use entity lookup."
        )

    cage_code = (cage_code or "").strip().upper()
    if not cage_code:
        return {"found": False, "cage_code": cage_code}

    params = {
        "api_key": api_key,
        "cageCode": cage_code,
        "includeSections": "entityRegistration,coreData,assertions",
    }

    try:
        resp = requests.get(SAM_ENTITY_URL, params=params, timeout=15)
        resp.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        if status == 403:
            raise requests.RequestException(
                f"SAM.gov API returned 403 — check that SAM_API_KEY is valid and enabled."
            ) from exc
        raise requests.RequestException(
            f"SAM.gov API returned HTTP {status} for CAGE {cage_code}."
        ) from exc
    except requests.Timeout:
        raise requests.RequestException(
            f"SAM.gov API timed out while looking up CAGE {cage_code}."
        )
    except requests.RequestException as exc:
        raise requests.RequestException(
            f"SAM.gov API request failed for CAGE {cage_code}: {exc}"
        ) from exc

    try:
        payload = resp.json()
    except ValueError:
        raise requests.RequestException(
            f"SAM.gov API returned non-JSON response for CAGE {cage_code}."
        )

    entity_list = payload.get("entityData") or []
    if not entity_list:
        return {"found": False, "cage_code": cage_code}

    entity = entity_list[0]
    reg        = entity.get("entityRegistration") or {}
    core       = entity.get("coreData") or {}
    assertions = entity.get("assertions") or {}

    # --- basic registration fields ---
    uei        = reg.get("ueiSAM") or ""
    legal_name = reg.get("legalBusinessName") or ""
    reg_status = reg.get("registrationStatus") or ""
    reg_expiry = reg.get("registrationExpirationDate") or ""
    excluded   = (reg.get("exclusionStatusFlag") or "N").upper() == "Y"

    # --- entity URL ---
    entity_info = core.get("entityInformation") or {}
    entity_url  = entity_info.get("entityURL") or ""

    # --- addresses ---
    def _parse_addr(raw):
        return {
            "street":  raw.get("addressLine1") or "",
            "street2": raw.get("addressLine2") or "",
            "city":    raw.get("city") or "",
            "state":   raw.get("stateOrProvinceCode") or "",
            "zip":     raw.get("zipCode") or "",
            "country": raw.get("countryCode") or "",
        }

    phys_raw = core.get("physicalAddress") or {}
    mail_raw = core.get("mailingAddress") or {}
    address         = _parse_addr(phys_raw)
    mailing_address = _parse_addr(mail_raw)
    # flag when mailing == physical so the template can say "same as physical"
    addresses_same  = address == mailing_address

    # --- business types ---
    biz_types_block = core.get("businessTypes") or {}
    biz_type_list   = biz_types_block.get("businessTypeList") or []
    business_types  = [
        bt.get("businessTypeDesc") or bt.get("businessTypeCode", "")
        for bt in biz_type_list
        if bt.get("businessTypeDesc") or bt.get("businessTypeCode")
    ]

    # --- set-aside flags ---
    # Primary source: sbaBusinessTypeList (SBA-certified programs)
    # Fallback: businessTypeList codes for SDVOSB/VOSB (VA certs pre-2023 migration)
    # Also: naicsList sbaSmallBusiness flag for small business size standard
    set_aside_flags = {
        "sdvosb": False,
        "hubzone": False,
        "wosb": False,
        "edwosb": False,
        "8a": False,
        "small_business": False,
    }
    sba_list = biz_types_block.get("sbaBusinessTypeList") or []
    for sba in sba_list:
        code = (sba.get("sbaBusinessTypeCode") or "").strip()
        key  = _SBA_CODE_MAP.get(code)
        if key:
            set_aside_flags[key] = True

    # Fallback: check businessTypeList using the restricted map only.
    # "27" (Self Certified SDB) is NOT 8(a) — _BIZ_TYPE_FALLBACK_MAP excludes it.
    for bt in biz_type_list:
        code = (bt.get("businessTypeCode") or "").strip()
        key  = _BIZ_TYPE_FALLBACK_MAP.get(code)
        if key:
            set_aside_flags[key] = True

    # --- NAICS codes (under assertions.goodsAndServices) ---
    goods = assertions.get("goodsAndServices") or {}
    naics_list = goods.get("naicsList") or []
    primary_naics = goods.get("primaryNaics") or ""
    naics_codes = [
        {
            "code":    n.get("naicsCode") or "",
            "desc":    n.get("naicsDescription") or "",
            "primary": (n.get("naicsCode") or "") == primary_naics,
            "small_business": (n.get("sbaSmallBusiness") or "").upper() == "Y",
        }
        for n in naics_list
        if n.get("naicsCode")
    ]
    # If any NAICS qualifies as SBA small business, set the flag
    if any(n["small_business"] for n in naics_codes):
        set_aside_flags["small_business"] = True

    # --- PSC codes (under assertions.goodsAndServices) ---
    psc_items = goods.get("pscList") or []
    psc_codes = [
        {
            "code": p.get("pscCode") or "",
            "desc": p.get("pscDescription") or "",
        }
        for p in psc_items
        if p.get("pscCode")
    ]

    # --- SAM.gov profile URL ---
    sam_url = f"https://sam.gov/entity/{uei}/core-data" if uei else "https://sam.gov"

    return {
        "found": True,
        "cage_code": cage_code,
        "legal_name": legal_name,
        "uei": uei,
        "registration_status": reg_status,
        "registration_expiry": reg_expiry,
        "entity_url": entity_url,
        "address": address,
        "mailing_address": mailing_address,
        "addresses_same": addresses_same,
        "business_types": business_types,
        "naics_codes": naics_codes,
        "psc_codes": psc_codes,
        "set_aside_flags": set_aside_flags,
        "exclusion_status": excluded,
        "sam_url": sam_url,
        "debug_sba_list": sba_list,  # temporary — remove after diagnosis
        "debug_raw_json": entity,    # temporary — full raw API entity object
    }


def _mailing_address_to_text(mailing: dict) -> str:
    """Serialize SAM mailing_address dict to a newline-separated string for TextField storage."""
    if not mailing or not isinstance(mailing, dict):
        return ""
    parts = []
    for key in ("street", "street2", "city", "state", "zip", "country"):
        v = (mailing.get(key) or "").strip()
        if v:
            parts.append(v)
    return "\n".join(parts)


def get_or_fetch_cage(cage_code, force_refresh=False):
    """
    Returns a SAMEntityCache instance for the given cage_code.

    Logic:
    1. If force_refresh is False, check for an existing non-stale cache record.
       If found, return it immediately — no API call.
    2. If missing, stale, or force_refresh=True, call lookup_cage() and
       upsert the result into SAMEntityCache.
    3. If lookup_cage() raises or returns an error payload, save a cache record
       with fetch_error=True so we don't hammer the API on every page load.
       Return that error record.

    Always returns a SAMEntityCache instance (never None, never raises).
    Callers check record.fetch_error to know if the data is valid.
    """
    from django.utils import timezone

    from sales.models.sam_cache import SAMEntityCache

    cage_code = (cage_code or "").strip().upper()

    if not force_refresh:
        try:
            record = SAMEntityCache.objects.get(pk=cage_code)
            if not record.is_stale():
                return record
        except SAMEntityCache.DoesNotExist:
            pass

    try:
        data = lookup_cage(cage_code)
    except Exception:
        logger.exception("get_or_fetch_cage: lookup_cage failed for CAGE %s", cage_code)
        data = {"error": "SAM API call failed", "cage_code": cage_code, "found": False}

    has_error = bool(data.get("error"))
    physical = data.get("address") or {}
    if not isinstance(physical, dict):
        physical = {}

    mailing = data.get("mailing_address")
    if isinstance(mailing, dict):
        mailing_text = _mailing_address_to_text(mailing)
    else:
        mailing_text = (mailing or "") if isinstance(mailing, str) else ""

    flags = data.get("set_aside_flags") or {}
    if isinstance(flags, dict):
        sba_flag_list = sorted(k for k, v in flags.items() if v)
    else:
        sba_flag_list = []

    record, _ = SAMEntityCache.objects.update_or_create(
        cage_code=cage_code,
        defaults={
            "entity_name": (data.get("legal_name") or "") if not has_error else "",
            "website": (data.get("entity_url") or "") if not has_error else "",
            "physical_address_line1": physical.get("street", "") if not has_error else "",
            "physical_address_line2": physical.get("street2", "") if not has_error else "",
            "physical_city": physical.get("city", "") if not has_error else "",
            "physical_state": physical.get("state", "") if not has_error else "",
            "physical_zip": physical.get("zip", "") if not has_error else "",
            "mailing_address": mailing_text if not has_error else "",
            "sba_flags": sba_flag_list,
            "naics_codes": (data.get("naics_codes") or []) if not has_error else [],
            "psc_codes": (data.get("psc_codes") or []) if not has_error else [],
            "raw_json": data if not has_error else dict(data),
            "last_fetched": timezone.now(),
            "fetch_error": has_error,
        },
    )
    return record
