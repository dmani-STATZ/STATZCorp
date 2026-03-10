"""
Sales app views. Dashboard redirects to solicitation list.
"""
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required

from sales.views.imports import import_upload
from sales.views.solicitations import solicitation_list
from sales.views.suppliers import backfill_nsn


@login_required
def dashboard(request):
    """Stub: redirect to solicitation list."""
    return redirect('sales:solicitation_list')


__all__ = ['dashboard', 'import_upload', 'solicitation_list', 'backfill_nsn']
