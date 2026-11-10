import copy
import logging
import os
import time
from decimal import Decimal, ROUND_HALF_UP

import requests
from django.db.models import F
from django.utils.timezone import now

logger = logging.getLogger(__name__)

# Claude model IDs: the ONLY place model strings may appear in application code.
CLAUDE_HAIKU_MODEL = "claude-haiku-5-5"
CLAUDE_SONNET_MODEL = "claude-sonnet-5-5"

ANTHROPIC_TIMEOUT_SECONDS = 120
MIN_MAX_TOKENS = 4096
SAMPLING_PARAMS = ("temperature", "top_p", "top_k")
NORMAL_STOP_REASONS = ("end_turn", "stop_sequence", "tool_use")

# Request settings applied by prepare_payload(). Models not listed pass through unchanged.
MODEL_REQUEST_DEFAULTS = {
    CLAUDE_HAIKU_MODEL: {
        "output_config": {"effort": "low"},
    },
    CLAUDE_SONNET_MODEL: {
        "thinking": {"type": "between_tools"},
        "output_config": {"effort": "medium"},
    },
}

_PER_MTOK = Decimal("1000000")

MODEL_PRICING = {
    CLAUDE_SONNET_MODEL: {"input": Decimal("2.00"), "output": Decimal("10.00")},
    CLAUDE_HAIKU_MODEL: {
        "input": Decimal("0.10"),
        "output": Decimal("0.50"),
        "long_context_threshold": 100_000,
        "long_context_input": Decimal("0.50"),
        "long_context_output": Decimal("2.50"),
    },
    # Legacy: retained so reverting the model constants still prices correctly.
    "claude-sonnet-4-6": {"input": Decimal("3.00"), "output": Decimal("15.00")},
    "claude-haiku-4-5-20251001": {"input": Decimal("1.00"), "output": Decimal("5.00")},
}
DEFAULT_PRICING = MODEL_PRICING[CLAUDE_SONNET_MODEL]

# Retry only HTTP 429; backoff before attempts 2 and 3 (then give up).
_RATE_LIMIT_MAX_ATTEMPTS = 3
_RATE_LIMIT_BACKOFF_SECONDS = (2.0, 8.0, 20.0)


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    rates = MODEL_PRICING.get(model, DEFAULT_PRICING)
    input_rate = rates["input"]
    output_rate = rates["output"]
    threshold = rates.get("long_context_threshold")
    if threshold is not None and input_tokens > threshold:
        input_rate = rates["long_context_input"]
        output_rate = rates["long_context_output"]
    cost = (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate) / _PER_MTOK
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def prepare_payload(payload: dict) -> dict:
    """Return a copy of payload adjusted for the target model. Never mutates the input."""
    prepared = copy.deepcopy(payload)
    model = prepared.get("model")
    defaults = MODEL_REQUEST_DEFAULTS.get(model)
    if defaults is None:
        return prepared

    for param in SAMPLING_PARAMS:
        if param in prepared:
            prepared.pop(param)
            logger.warning("Removed unsupported param %r from Anthropic payload (model=%s)", param, model)

    if "thinking" in defaults and "thinking" not in prepared:
        prepared["thinking"] = copy.deepcopy(defaults["thinking"])

    if "output_config" in defaults:
        output_config = prepared.setdefault("output_config", {})
        for key, value in defaults["output_config"].items():
            output_config.setdefault(key, value)

    prepared["max_tokens"] = max(int(prepared.get("max_tokens") or 0), MIN_MAX_TOKENS)
    return prepared


def extract_text(body: dict) -> str:
    """Concatenate all text blocks in order; ignore thinking and any other block types."""
    return "".join(
        block.get("text", "")
        for block in (body.get("content") or [])
        if block.get("type") == "text"
    )


def record_api_usage(model: str, input_tokens: int, output_tokens: int, call_site: str) -> None:
    try:
        from core.models import APIBudget, APIUsageLog

        cost = calculate_cost(model, input_tokens, output_tokens)
        APIUsageLog.objects.create(
            call_site=call_site,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost
        )
        APIBudget.get()  # Ensure singleton exists
        APIBudget.objects.filter(pk=1).update(
            balance_usd=F('balance_usd') - cost,
            updated_at=now()
        )
    except Exception:
        # A failure here must NEVER raise or interrupt the caller
        pass


def _log_http_error(response, call_site: str, payload: dict) -> None:
    logger.error(
        "Anthropic API error %s at %s (model=%s): %s",
        response.status_code, call_site, payload.get("model"), response.text[:2000],
    )


def call_anthropic(payload: dict, call_site: str, timeout: float | None = None) -> dict:
    payload = prepare_payload(payload)
    timeout = timeout or ANTHROPIC_TIMEOUT_SECONDS
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": api_key,
    }

    url = "https://api.anthropic.com/v1/messages"
    response = None

    for attempt in range(_RATE_LIMIT_MAX_ATTEMPTS):
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)

        if response.status_code == 429:
            if attempt < _RATE_LIMIT_MAX_ATTEMPTS - 1:
                time.sleep(_RATE_LIMIT_BACKOFF_SECONDS[attempt])
                continue
            _log_http_error(response, call_site, payload)
            response.raise_for_status()

        if not response.ok:
            _log_http_error(response, call_site, payload)
            response.raise_for_status()
        break

    response_body = response.json()

    # On success only: extract usage and debit APIBudget once.
    usage = response_body.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    record_api_usage(payload["model"], input_tokens, output_tokens, call_site)

    stop_reason = response_body.get("stop_reason")
    if stop_reason not in NORMAL_STOP_REASONS:
        logger.warning(
            "Anthropic call %s ended with stop_reason=%s (model=%s)",
            call_site, stop_reason, payload.get("model"),
        )

    return response_body
