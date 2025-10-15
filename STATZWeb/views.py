"""
Main views for STATZWeb application.
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.conf import settings
from .system_test_utils import run_system_tests
from .version_utils import get_version_info, get_display_version


def landing(request):
    """Landing page view."""
    return render(request, 'landing.html')


def index(request):
    """Main index page view."""
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


def add_announcement(request):
    """Placeholder for add announcement view."""
    return render(request, 'add_announcement.html')


def delete_announcement(request, announcement_id):
    """Placeholder for delete announcement view."""
    return render(request, 'delete_announcement.html', {'announcement_id': announcement_id})