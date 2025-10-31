"""
Main views for STATZWeb application.
"""

from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.conf import settings
from users.forms import PortalResourceForm, PortalSectionForm, WorkCalendarEventForm, WorkCalendarTaskForm
from users.models import Announcement
from users.portal_services import build_portal_context
from .system_test_utils import run_system_tests
from .version_utils import get_version_info, get_display_version


def landing(request):
    """Landing page view."""
    return render(request, 'landing.html')


def index(request):
    """Main index page view."""
    portal_context = build_portal_context(request.user)
    announcement_qs = Announcement.objects.select_related('posted_by').order_by('-posted_at')[:10]
    announcement_payload = [
        {
            'id': announcement.id,
            'title': announcement.title,
            'content': announcement.content,
            'posted_at': announcement.posted_at.isoformat(),
            'posted_by': announcement.posted_by.get_full_name() or announcement.posted_by.username,
        }
        for announcement in announcement_qs
    ]
    context = {
        'announcements': announcement_qs,
        'announcement_payload': announcement_payload,
        'portal_context': portal_context,
        'portal_section_form': PortalSectionForm(),
        'portal_resource_form': PortalResourceForm(),
        'portal_task_form': WorkCalendarTaskForm(),
        'portal_event_form': WorkCalendarEventForm(),
    }
    return render(request, 'index.html', context)


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
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    data = request.POST or request.body
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
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    announcement = get_object_or_404(Announcement, pk=announcement_id)
    announcement.delete()
    return JsonResponse({'success': True})
