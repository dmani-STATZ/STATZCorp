"""Cache-only CAGE name lookup for the solicitation workspace."""
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from quote.services.cage_names import normalize_cage, resolve_cages, workspace_display

_CAGE_RE = re.compile(r'^[A-Z0-9]{5}$')
_MAX_CAGES = 50


@login_required
@require_GET
def cage_names(request):
    """GET /quote/cages/names/?cage= — SAM cache and directory only, never a SAM call."""
    valid = []
    seen = set()
    for raw in request.GET.getlist('cage'):
        cage = normalize_cage(raw)
        if not _CAGE_RE.match(cage) or cage in seen:
            continue
        seen.add(cage)
        valid.append(cage)
        if len(valid) >= _MAX_CAGES:
            break
    if not valid:
        return JsonResponse({'names': {}})
    resolved = resolve_cages(valid)
    return JsonResponse({
        'names': {cage: workspace_display(resolved[cage]) for cage in valid},
    })
