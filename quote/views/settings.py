"""Quotes Settings page. Superusers only; the services decide what a save does."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from quote.models import QuoteSenderBlock
from quote.services import app_settings, blocklist


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


@login_required
@require_POST
def settings_block_add(request):
    _superuser(request)
    try:
        blocklist.add_block(
            request.POST.get('block_type', ''),
            request.POST.get('value', ''),
            request.POST.get('label', ''),
            request.POST.get('reason', ''),
            supplier=None,
            user=request.user,
        )
    except blocklist.BlockInvalid as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'Blocked.')
    return redirect('quote:settings')


@login_required
@require_POST
def settings_block_deactivate(request, block_id):
    _superuser(request)
    block = get_object_or_404(QuoteSenderBlock, pk=block_id)
    blocklist.deactivate_block(block, request.user)
    messages.success(
        request,
        'Unblocked. Their new emails will be scanned again; use Scan quote on older ones.',
    )
    return redirect('quote:settings')
