"""Quotes Settings page. Superusers only; the services decide what a save does."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from quote.services import app_settings


def _superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


@login_required
def settings_page(request):
    """GET /quote/settings/ -- the three cards."""
    _superuser(request)
    return render(request, 'quote/settings/index.html', {
        'section': 'settings',
        **app_settings.page_context(),
    })


@login_required
@require_POST
def settings_save(request):
    """POST /quote/settings/save/ -- one card, all or nothing."""
    _superuser(request)
    section = request.POST.get('section', '')
    result = app_settings.save_section(section, request.POST, request.user)
    if result.ok:
        messages.success(request, 'Settings saved.')
        return redirect('quote:settings')
    return render(request, 'quote/settings/index.html', {
        'section': 'settings',
        **app_settings.page_context(values=result.values, errors=result.errors),
    })
