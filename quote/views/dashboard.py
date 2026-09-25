"""Quotes dashboard — placeholder shell while the Phase 1-4 screens are built."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    """Landing page for the Quotes app."""
    return render(request, 'quote/dashboard.html', {'section': 'dashboard'})
