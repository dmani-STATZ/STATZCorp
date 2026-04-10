import json
import os
import re

from anthropic import Anthropic

from .dibbs_pdf import extract_pdf_text

MODELS = {
    "haiku45":  "claude-haiku-4-5-20251001",
    "sonnet46": "claude-sonnet-4-6",
    "opus46":   "claude-opus-4-6",
}

SYSTEM_PROMPT = """You are a government procurement analyst specializing in DLA (Defense Logistics Agency) solicitations.
Your job is to extract specific bid-critical information from DIBBS solicitation documents.
You must respond ONLY with a valid JSON object. No preamble, no explanation, no markdown code fences.
All boolean fields must be true or false. All string fields must be a string or null if not found."""

USER_PROMPT_TEMPLATE = """Analyze the following DIBBS solicitation document text for solicitation {sol_number}.

Extract the following fields and return them as a JSON object:

{{
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
  "other_notable_requirements": <array of strings — any other notable requirements not covered above, each as a brief plain-English statement. Empty array if none.>
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


def analyze_solicitation_pdf(pdf_blob_bytes: bytes, solicitation_number: str, model_key: str) -> dict:
    """
    Extract bid-critical requirements from a DIBBS solicitation PDF
    using the specified Claude model.

    model_key must be one of: haiku35, haiku45, sonnet45, opus45

    Returns a dict of extracted fields plus _usage and _model_key metadata.
    Raises ValueError on bad input, Exception on API failure.
    """
    if model_key not in MODELS:
        raise ValueError(
            f"Unknown model_key '{model_key}'. Must be one of: {list(MODELS.keys())}"
        )

    pdf_text = extract_pdf_text(pdf_blob_bytes)
    if not pdf_text:
        raise ValueError("No text could be extracted from the PDF blob.")

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    user_prompt = USER_PROMPT_TEMPLATE.format(
        sol_number=solicitation_number,
        pdf_text=_extract_sections_ab(pdf_text),
    )

    message = client.messages.create(
        model=MODELS[model_key],
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown fences if model returns them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)

    result["_usage"] = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "model": message.model,
        "model_key": model_key,
    }

    return result
