# OpenRouter Usage in STATZCorp

This document summarizes how we integrate OpenRouter for supplier enrichment and how to extend it elsewhere in the project.

## What we use OpenRouter for
- Extracting supplier metadata from raw website HTML (company name, logo URL, addresses, phone numbers, emails, CAGE code, social links, notes).
- Returning structured JSON that downstream UI can apply to supplier records.
- Providing a manual-mode fallback where users can run the generated prompt in their own LLM and paste the JSON result.

## Key Django components
- `suppliers/views.py`
  - `build_supplier_prompt_bundle(html)`: builds system/user messages, truncates/sanitizes HTML.
  - `call_openrouter_for_supplier(html, model_override=None, prompt_bundle=None)`: posts to OpenRouter chat/completions with model, messages, temperature 0.2, and optional fallbacks.
  - `SupplierEnrichView (GET)`: fetches website HTML, builds prompt, calls OpenRouter unless manual_only. Returns HTML, AI result/error, prompt context, model info. Auto-saves `logo_url` and `last_enriched_at` if provided, and updates audit fields.
  - `SupplierApplyEnrichmentView (POST)`: applies a single field (logo_url, phones, emails, website_url, cage_code, or addresses). Creates one Address instance and can attach to multiple address types. Updates `last_enriched_at`, `modified_on`, and `modified_by` when available.
  - `GlobalAIModelConfigView`: gets/sets shared model configuration (superuser gated).
  - `sanitize_html_for_enrichment`: strips `<style>` blocks before prompting to reduce noise.
  - Address parsing helpers (`_parse_address_text`, `_normalize_addresses`) and JSON cleanup (`_extract_json_payload`).
- `suppliers/openrouter_config.py` (not shown here): handles stored model, fallback list, and selection logic.

## Settings and environment
- Required:
  - `OPENROUTER_API_KEY`: Bearer token for requests.
- Optional:
  - `OPENROUTER_BASE_URL` (default `https://openrouter.ai/api/v1`)
  - `OPENROUTER_HTTP_REFERER`, `OPENROUTER_X_TITLE` (branding/attribution headers)
  - `OPENROUTER_MODEL_FALLBACKS`: comma-separated list or iterable of fallback model slugs
- Model selection:
  - `get_model_for_request(model_override)` chooses the explicit override or the stored/effective default.
  - Payload includes `model` and, if present, `models` for fallbacks.

## Prompt structure
- System prompt: instructs the model to extract JSON with fields:
  - `company_name`, `logo_url`, `addresses`, `phone_numbers`, `emails`, `cage_code`, `website_url`, `social_links`, `notes`
- User prompt: includes the sanitized/truncated HTML (max 120k chars) and reiterates JSON-only response requirements.
- We attempt to parse code-fenced or loosely formatted JSON responses with `_extract_json_payload`.

## Front-end flow (`templates/suppliers/supplier_enrich.html`)
- User can save/update website URL, pick an OpenRouter model override, or toggle manual mode.
- Fetches `/suppliers/<pk>/enrich/` to retrieve HTML, AI result, model info, and the combined prompt.
- Offers “Copy Context Prompt” for manual runs; allows pasting manual JSON to render/apply suggestions.
- Suggestions render as cards for addresses, phones, emails, and CAGE; each card lets the user map a suggested value to a specific supplier field and apply via POST `/suppliers/<pk>/apply-enrichment/`.
- Raw JSON and HTML are shown in accordions (default closed) to reduce clutter.

## Database fields touched
- Supplier:
  - `logo_url`, `primary_phone`, `business_phone`, `business_fax`, `primary_email`, `business_email`, `website_url`, `cage_code`
  - `last_enriched_at`, `modified_on`, `modified_by` (when available)
- Address:
  - `address_line_1`, `address_line_2`, `city`, `state`, `zip`
  - One Address instance can be attached to multiple supplier address types (physical, shipping, billing).

## Error handling & validation
- URL validation: only http/https; auto-prepends https if missing scheme.
- Network timeouts: 15s connect / 120s read for OpenRouter; 10s default for website fetch.
- JSON parsing: tolerant of fenced/extra text; raises if no JSON object can be parsed.
- Manual mode skips OpenRouter call but returns prompt/context so users can run elsewhere.

## Security & hygiene
- API key pulled from settings/env; not exposed to the client.
- Headers support `HTTP-Referer` and `X-Title` for attribution if required by OpenRouter policy.
- Sanitization: strip `<style>` from HTML before sending to the model; truncation to 120k chars.

## Extending to other features
- Reuse `call_openrouter_for_supplier` as a pattern:
  - Build a focused system prompt with a strict JSON schema.
  - Include sanitized, size-limited context.
  - Normalize/validate the returned JSON on the server before applying.
- Centralize model config: continue using `GlobalAIModelConfigView` pattern for other apps.
- Keep manual-mode parity: always provide the combined prompt and accept pasted JSON for non-OpenRouter users.

## Quick checklist to expand usage
- Add a system prompt with explicit JSON schema.
- Sanitize/limit input context (HTML/text) before calling OpenRouter.
- Expose a manual mode and copyable prompt.
- Normalize and validate fields on the server; allow selective apply via POST.
- Update audit fields (`modified_by`, `modified_on`, `last_enriched_at`) on any writes.
- Respect model overrides, stored defaults, and fallbacks; keep keys in settings/env only.

