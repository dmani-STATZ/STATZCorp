from django import template

from ..config import IMPORT_TARGETS

register = template.Library()


@register.filter
def confidence_pct(value):
    if value is None:
        return None
    return round(float(value) * 100.0)


@register.filter
def imports_get_item(mapping, key):
    if not mapping:
        return ''
    return mapping.get(key, '')


@register.simple_tag
def import_target_label(key):
    cfg = IMPORT_TARGETS.get(key)
    if cfg:
        return cfg.get('label') or key
    return key


@register.inclusion_tag('imports/partials/unresolved_fk_panel.html')
def unresolved_fk_panel(unresolved_fk_fields, rows, session):
    panel = []
    for sheet_col, model_field in unresolved_fk_fields:
        seen = set()
        vals = []
        for row in rows:
            rd = row.raw_data or {}
            pc = row.proposed_changes or {}
            raw_val = rd.get(sheet_col, '')
            if raw_val and str(raw_val).strip() and model_field not in pc:
                s = str(raw_val).strip()
                if s not in seen:
                    seen.add(s)
                    vals.append(s)
        if vals:
            panel.append({
                'sheet_col': sheet_col,
                'model_field': model_field,
                'raw_values': vals,
            })
    return {'panel': panel, 'session': session}
