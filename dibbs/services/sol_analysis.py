import json
import logging
import re

from core.anthropic_client import (
    CLAUDE_HAIKU_MODEL,
    CLAUDE_SONNET_MODEL,
    call_anthropic,
    extract_text,
)

from .dibbs_pdf import extract_pdf_text

logger = logging.getLogger(__name__)

MODELS = {"haiku55": CLAUDE_HAIKU_MODEL, "sonnet55": CLAUDE_SONNET_MODEL}
DEFAULT_MODEL_KEY = "haiku55"

SYSTEM_PROMPT = """You are a government procurement analyst specializing in DLA (Defense Logistics Agency) solicitations.
Your job is to extract specific bid-critical information from DIBBS solicitation documents.
You must respond ONLY with a valid JSON object. No preamble, no explanation, no markdown code fences.
All boolean fields must be true or false. All string fields must be a string or null if not found."""

USER_PROMPT_TEMPLATE = """Analyze the following DIBBS solicitation document text for solicitation {sol_number}.

Extract the following fields and return them as a JSON object:

{{
  "date_issued": <string or null — date the solicitation was issued in YYYY-MM-DD format>,
  "fat_required": <true/false — is First Article Test (FAT) required?>,
  "fat_units": <integer or null — how many units must be tested for FAT?>,
  "fat_days": <integer or null — how many calendar days to submit FAT report?>,
  "fat_summary": <string or null — one sentence plain-English summary of the FAT requirement>,
  "itar_export_control": <true/false — does the document mention ITAR or export control of technical data?>,
  "origin_inspection_required": <true/false — is inspection required at origin (contractor facility)?>,
  "iso_9001_required": <true/false — is ISO 9001:2015 or equivalent required?>,
  "buy_american_applies": <true/false — does Buy American Act or Berry Amendment apply?>,
  "additive_manufacturing_prohibited": <true/false — is additive manufacturing prohibited unless approved?>,
  "cmmc_required": <true/false — is CMMC (Cybersecurity Maturity Model Certification) required?>,
  "cmmc_level": <integer or null — what level of CMMC is required?>,
  "delivery_destination": <string or null — name and city/state of delivery destination facility>,
  "need_ship_date": <string or null — Need Ship Date in YYYY-MM-DD format>,
  "required_delivery_date": <string or null — Original Required Delivery Date in YYYY-MM-DD format>,
  "fob_point": <string or null — FOB Origin or FOB Destination>,
  "packaging_standard": <string or null — packaging standard cited e.g. MIL-STD-2073-1E>,
  "preservation_method": <string or null — preservation method code or description if stated>,
  "special_packaging_instructions": <string or null — any supplemental or special packaging instructions verbatim>,
  "marking_standard": <string or null — marking standard cited e.g. MIL-STD-129>,
  "quantity_ranges_encouraged": <true/false — does the solicitation encourage submitting quantity ranges?>,
  "dpas_rating": <string or null — DPAS priority rating code found in the RATING block of the SF-18 cover page e.g. DO-C9 or DX-C9. If not present return null>,
  "buyer_name": <string or null — the buyer or contracting officer name from the Issued By block on the SF-18 cover page. Usually follows "Name:" label>,
  "buyer_email": <string or null — buyer email address from the Issued By block. Usually follows "Email:" label>,
  "buyer_phone": <string or null — buyer phone number from the Issued By block. Usually follows "Tel:" label>,
  "issuing_office": <string or null — DLA office name and division from the Issued By block e.g. "DLA Land and Maritime, Fluid Handling Division">,
  "issue_date": <string or null — the date this solicitation was issued, found in block 2 of the SF-18 cover page labeled DATE ISSUED. Return in YYYY-MM-DD format e.g. 2026-03-30>,
  "other_notable_requirements": <array of strings — any other notable requirements not covered above, each as a brief plain-English statement. Empty array if none.>,
  "extraction_confidence": <"HIGH", "MEDIUM", or "LOW" — your overall confidence in the accuracy of this extraction. HIGH = all key fields found clearly stated in the document. MEDIUM = most fields found but one or more required inference or were ambiguous. LOW = significant portions of the document were unclear, missing, or contradictory>,
  "extraction_notes": <string or null — brief plain-English explanation of any fields you were uncertain about, could not find, or had to infer. null if confidence is HIGH and all fields were clearly stated>
}}

Solicitation text:
{pdf_text}"""


def _extract_sections_ab(pdf_text: str) -> str:
    """
    Extract only Section A and Section B content from DIBBS solicitation PDF text.

    Strategy:
    1. Find the start of SECTION A using a case-insensitive regex
    2. Find the first occurrence of a section that is NOT A or B
       (e.g. SECTION C, SECTION D, SECTION F, etc.)
    3. Return the slice between those two points

    Fallback: if SECTION A cannot be located, return the first 12,000
    characters of the full text so the LLM still gets something useful.
    """
    # Match "SECTION A" or "SECTION B" as a section header —
    # appears as standalone bold/centered text in DIBBS PDFs.
    # Use word boundary to avoid matching "SECTION A continued" mid-line.
    section_a_pattern = re.compile(r"SECTION\s+A\b", re.IGNORECASE)
    # Match any section letter that is NOT A or B
    non_ab_pattern = re.compile(
        r'(?:^|\n)\s*SECTION\s+[C-Z]\s*[-–]\s*[A-Z]',
        re.MULTILINE
    )

    a_match = section_a_pattern.search(pdf_text)
    if not a_match:
        # Fallback: no section markers found, send first 12,000 chars
        return pdf_text[:12000]

    start = a_match.start()
    preamble = pdf_text[:start].strip()

    # Find first non-A/B section after the start of Section A
    end_match = non_ab_pattern.search(pdf_text, start)
    if end_match:
        end = end_match.start()
    else:
        # No terminating section found — send everything from Section A onward
        end = len(pdf_text)

    extracted = pdf_text[start:end].strip()

    # Safety valve: if extracted text is unreasonably short (< 500 chars),
    # the regex probably misfired — fall back to 12,000 char truncation
    if len(extracted) < 500:
        return pdf_text[:12000]

    if preamble:
        return preamble + "\n\n" + extracted
    return extracted


def analyze_solicitation_pdf(
    pdf_blob_bytes: bytes, solicitation_number: str, model_key: str = DEFAULT_MODEL_KEY
) -> dict:
    """
    Extract bid-critical requirements from a DIBBS solicitation PDF
    using the specified Claude model.

    model_key is a key of MODELS (haiku55, sonnet55). Unknown keys log a
    warning and fall back to DEFAULT_MODEL_KEY.

    Returns a dict of extracted fields plus _usage and _model_key metadata.
    Raises ValueError on bad input, Exception on API failure.
    """
    model = MODELS.get(model_key)
    if model is None:
        logger.warning(
            "Unknown sol_analysis model_key %r; falling back to %r", model_key, DEFAULT_MODEL_KEY
        )
        model_key = DEFAULT_MODEL_KEY
        model = MODELS[DEFAULT_MODEL_KEY]

    pdf_text = extract_pdf_text(pdf_blob_bytes)
    if not pdf_text:
        raise ValueError("No text could be extracted from the PDF blob.")

    user_prompt = USER_PROMPT_TEMPLATE.format(
        sol_number=solicitation_number,
        pdf_text=_extract_sections_ab(pdf_text),
    )

    payload = {
        "model": model,
        "max_tokens": 1500,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    body = call_anthropic(payload, "dibbs.sol_analysis.analyze_solicitation_pdf")

    raw = extract_text(body).strip()

    # Strip markdown fences if model returns them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)

    usage = body.get("usage") or {}
    result["_usage"] = {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "model": body.get("model", model),
        "model_key": model_key,
    }

    return result


def save_analysis_result(solicitation, result: dict, model_key: str) -> None:
    """
    Persist LLM extraction result to dibbs_sol_analysis.
    Creates or replaces the row for this solicitation.
    Date fields are parsed from YYYY-MM-DD strings; invalid dates stored as None.
    other_notable_requirements stored as JSON text.
    """
    import json as _json
    from datetime import datetime

    from dibbs.models.sol_analysis import SolAnalysis

    def parse_date(val):
        if not val:
            return None
        try:
            return datetime.strptime(val, "%Y-%m-%d").date()
        except Exception:
            return None

    usage = result.get("_usage", {})

    SolAnalysis.objects.update_or_create(
        solicitation=solicitation,
        defaults={
            "model_key": model_key,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            # Page 1
            "issue_date": parse_date(result.get("issue_date")),
            "dpas_rating": result.get("dpas_rating"),
            "issuing_office": result.get("issuing_office"),
            "buyer_name": result.get("buyer_name"),
            "buyer_email": result.get("buyer_email"),
            "buyer_phone": result.get("buyer_phone"),
            # Critical
            "fat_required": result.get("fat_required"),
            "fat_units": result.get("fat_units"),
            "fat_days": result.get("fat_days"),
            "fat_summary": result.get("fat_summary"),
            "itar_export_control": result.get("itar_export_control"),
            "origin_inspection_required": result.get("origin_inspection_required"),
            "iso_9001_required": result.get("iso_9001_required"),
            "buy_american_applies": result.get("buy_american_applies"),
            "additive_manufacturing_prohibited": result.get(
                "additive_manufacturing_prohibited"
            ),
            "cmmc_required": result.get("cmmc_required"),
            "cmmc_level": result.get("cmmc_level"),
            "quantity_ranges_encouraged": result.get("quantity_ranges_encouraged"),
            # Delivery
            "fob_point": result.get("fob_point"),
            "delivery_destination": result.get("delivery_destination"),
            "need_ship_date": parse_date(result.get("need_ship_date")),
            "required_delivery_date": parse_date(result.get("required_delivery_date")),
            # Packaging
            "packaging_standard": result.get("packaging_standard"),
            "preservation_method": result.get("preservation_method"),
            "special_packaging_instructions": result.get(
                "special_packaging_instructions"
            ),
            "marking_standard": result.get("marking_standard"),
            # Other
            "other_notable_requirements": _json.dumps(
                result.get("other_notable_requirements") or []
            ),
            "extraction_confidence": result.get("extraction_confidence"),
            "extraction_notes": result.get("extraction_notes"),
        },
    )
