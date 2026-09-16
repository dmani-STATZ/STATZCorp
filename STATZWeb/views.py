"""
Main views for STATZWeb application.
"""

from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_http_methods
from django.conf import settings
from users.models import Announcement
from users.sharepoint_services import sync_sharepoint_calendar_two_way
from .system_test_utils import run_system_tests
from .version_utils import get_version_info, get_display_version


def landing(request):
    """Landing page view."""
    return render(request, 'landing.html')


def index(request):
    """Render the authenticated search-and-favorites portal home."""
    return render(request, 'index.html')


def about(request):
    """About page view."""
    return render(request, 'about.html')


@require_http_methods(["GET"])
def system_test(request):
    """
    System test page for verifying database connections and Azure environment.
    This page is open to all users for system health verification.
    """
    # Run system tests
    test_results, summary = run_system_tests()
    
    context = {
        'test_results': test_results,
        'summary': summary,
        'version_info': get_version_info(),
        'display_version': get_display_version(),
        'user_authenticated': request.user.is_authenticated,
        'user_is_superuser': request.user.is_superuser,
    }
    
    return render(request, 'system_test.html', context)


@require_http_methods(["GET"])
def system_test_api(request):
    """
    API endpoint for system test results (JSON format).
    Useful for automated testing or AJAX requests.
    This endpoint is open to all users for system health verification.
    """
    # Run system tests
    test_results, summary = run_system_tests()
    
    # Convert results to JSON-serializable format
    results_data = []
    for result in test_results:
        results_data.append({
            'test_name': result.test_name,
            'success': result.success,
            'message': result.message,
            'details': result.details,
            'timestamp': result.timestamp.isoformat(),
        })
    
    return JsonResponse({
        'results': results_data,
        'summary': summary,
        'version_info': get_version_info(),
        'user_authenticated': request.user.is_authenticated,
        'user_is_superuser': request.user.is_superuser,
    })


@login_required
@require_http_methods(["POST"])
def add_announcement(request):
    """Create a new announcement from portal form submissions."""
    if not request.user.has_perm('users.add_announcement'):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    if request.content_type == 'application/json':
        try:
            import json
            payload = json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            payload = {}
    else:
        payload = request.POST

    title = (payload.get('title') or '').strip()
    content = (payload.get('content') or '').strip()

    if not title or not content:
        return JsonResponse({'error': 'Title and content are required.'}, status=400)

    announcement = Announcement.objects.create(
        title=title,
        content=content,
        posted_by=request.user,
    )

    return JsonResponse({
        'announcement': {
            'id': announcement.id,
            'title': announcement.title,
            'content': announcement.content,
            'posted_at': announcement.posted_at.isoformat(),
            'posted_by': request.user.get_full_name() or request.user.username,
        }
    },
        status=201)


@login_required
@require_http_methods(["POST"])
def delete_announcement(request, announcement_id):
    """Delete an existing announcement."""
    if not request.user.has_perm('users.delete_announcement'):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    announcement = get_object_or_404(Announcement, pk=announcement_id)
    announcement.delete()
    return JsonResponse({'success': True})


@login_required
@user_passes_test(lambda u: u.is_superuser)
@require_http_methods(["POST"])
def sharepoint_sync_view(request):
    """Run two-way SharePoint list sync for work calendar events (Microsoft Graph)."""
    try:
        result = sync_sharepoint_calendar_two_way()
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
