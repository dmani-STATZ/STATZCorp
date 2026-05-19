import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from contracts.models import POSnippet


def _get_company(request):
    company = getattr(request, 'active_company', None)
    if not company:
        raise PermissionError("No active company")
    return company


@login_required
@require_http_methods(["GET"])
def po_snippet_list(request):
    """Return all snippets for the active company as JSON."""
    company = _get_company(request)
    snippets = list(
        POSnippet.objects.filter(company=company).values(
            'id', 'title', 'category', 'body', 'sort_order'
        )
    )
    return JsonResponse({'snippets': snippets})


@login_required
@require_http_methods(["POST"])
def po_snippet_create(request):
    """Create a new snippet for the active company."""
    company = _get_company(request)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').strip()
    if not title or not body:
        return JsonResponse({'error': 'title and body are required'}, status=400)

    snippet = POSnippet.objects.create(
        company=company,
        title=title,
        category=(data.get('category') or '').strip(),
        body=body,
        sort_order=int(data.get('sort_order') or 0),
    )
    return JsonResponse({
        'id': snippet.id,
        'title': snippet.title,
        'category': snippet.category,
        'body': snippet.body,
        'sort_order': snippet.sort_order,
    }, status=201)


@login_required
@require_http_methods(["POST"])
def po_snippet_update(request, pk):
    """Update an existing snippet (must belong to active company)."""
    company = _get_company(request)
    snippet = get_object_or_404(POSnippet, pk=pk, company=company)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').strip()
    if not title or not body:
        return JsonResponse({'error': 'title and body are required'}, status=400)

    snippet.title = title
    snippet.category = (data.get('category') or '').strip()
    snippet.body = body
    snippet.sort_order = int(data.get('sort_order') or 0)
    snippet.save()
    return JsonResponse({
        'id': snippet.id,
        'title': snippet.title,
        'category': snippet.category,
        'body': snippet.body,
        'sort_order': snippet.sort_order,
    })


@login_required
@require_http_methods(["POST"])
def po_snippet_delete(request, pk):
    """Delete a snippet (must belong to active company)."""
    company = _get_company(request)
    snippet = get_object_or_404(POSnippet, pk=pk, company=company)
    snippet.delete()
    return JsonResponse({'deleted': pk})
