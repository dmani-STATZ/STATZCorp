import os
from typing import Dict, Tuple, Optional

from django.conf import settings

from .models import OpenRouterModelSetting

DEFAULT_MODEL = "mistralai/mistral-small:free"


def _env_default_model() -> str:
    env_value = getattr(settings, "OPENROUTER_MODEL", os.environ.get("OPENROUTER_MODEL", "")).strip()
    return env_value or DEFAULT_MODEL


def _serialize_setting(setting: OpenRouterModelSetting) -> Dict:
    stored_model = (setting.model_name or "").strip()
    fallback_model = _env_default_model()
    effective_model = stored_model or fallback_model
    return {
        "stored_model": stored_model,
        "effective_model": effective_model,
        "needs_update": bool(setting.needs_update),
        "has_stored_model": bool(stored_model),
        "fallback_model": fallback_model,
        "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
        "updated_at_display": setting.updated_at.strftime("%Y-%m-%d %H:%M") if setting.updated_at else "",
        "updated_by": setting.updated_by.get_username() if setting.updated_by else "",
    }


def get_openrouter_model_info() -> Dict:
    setting = OpenRouterModelSetting.get_default()
    return _serialize_setting(setting)


def get_model_for_request(preferred: Optional[str] = None) -> Tuple[str, Dict]:
    info = get_openrouter_model_info()
    candidate = (preferred or info["stored_model"] or info["fallback_model"] or DEFAULT_MODEL).strip()
    return candidate or DEFAULT_MODEL, info


def save_openrouter_model_config(
    *,
    model_name: Optional[str] = None,
    needs_update: Optional[bool] = None,
    user=None,
) -> Dict:
    setting = OpenRouterModelSetting.get_default()
    changed = False
    if model_name is not None:
        setting.model_name = (model_name or "").strip()
        changed = True
    if needs_update is not None:
        setting.needs_update = bool(needs_update)
        changed = True
    if changed:
        if user and getattr(user, "is_authenticated", False):
            setting.updated_by = user
        setting.save()
    return _serialize_setting(setting)
