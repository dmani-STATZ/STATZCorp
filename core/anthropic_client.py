import os
from decimal import Decimal
from django.utils.timezone import now
from django.db.models import F
import requests

MODEL_PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000},
    "claude-haiku-4-5-20251001": {"input": 1.00 / 1_000_000, "output": 5.00 / 1_000_000},
}
DEFAULT_PRICING = {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000}

def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
    input_rate = Decimal(str(pricing["input"]))
    output_rate = Decimal(str(pricing["output"]))
    cost = (Decimal(input_tokens) * input_rate) + (Decimal(output_tokens) * output_rate)
    return cost.quantize(Decimal("0.000001"))

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
        APIBudget.get() # Ensure singleton exists
        APIBudget.objects.filter(pk=1).update(
            balance_usd=F('balance_usd') - cost,
            updated_at=now()
        )
    except Exception:
        # A failure here must NEVER raise or interrupt the caller
        pass

def call_anthropic(payload: dict, call_site: str) -> dict:
    # Import guards inside the function body to avoid Django app-registry issues
    from core.models import APIBudget, APIUsageLog

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": api_key,
    }
    
    url = "https://api.anthropic.com/v1/messages"
    
    # payload is a dict, requests expects json keyword parameter for automatic serialization
    response = requests.post(url, json=payload, headers=headers, timeout=30)
    
    if not response.ok:
        response.raise_for_status()
        
    response_body = response.json()
    
    # On success: extract usage and record API usage
    usage = response_body.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    model = payload.get("model", "")
    
    record_api_usage(model, input_tokens, output_tokens, call_site)
    
    return response_body
