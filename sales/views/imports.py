"""
Daily DIBBS import upload view.
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator

from sales.forms import ImportUploadForm
from sales.services.importer import run_import
from sales.models import ImportBatch


@login_required
def import_upload(request):
    """
    GET:  render upload form
    POST: validate form, call run_import(), render result summary
    """
    if request.method != 'POST':
        form = ImportUploadForm()
        return render(request, 'sales/import/upload.html', {
            'form': form,
            'page_title': 'Daily Import',
        })

    form = ImportUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, 'Please correct the errors below.')
        return render(request, 'sales/import/upload.html', {
            'form': form,
            'page_title': 'Daily Import',
        })

    in_file = form.cleaned_data['in_file']
    bq_file = form.cleaned_data['bq_file']
    as_file = form.cleaned_data['as_file']
    imported_by = request.user.get_full_name() or request.user.get_username() or ''

    try:
        result = run_import(in_file, bq_file, as_file, imported_by=imported_by)
    except Exception as e:
        messages.error(request, f'Import failed: {e}')
        return render(request, 'sales/import/upload.html', {
            'form': form,
            'page_title': 'Daily Import',
        })

    context = {
        'form': ImportUploadForm(),
        'result': result,
        'page_title': 'Daily Import',
    }
    if result.get('match_summary'):
        by_tier = result['match_summary'].get('by_tier', {})
        context['match_tier_1'] = by_tier.get(1, 0)
        context['match_tier_2'] = by_tier.get(2, 0)
        context['match_tier_3'] = by_tier.get(3, 0)
    return render(request, 'sales/import/upload.html', context)


@login_required
def import_history(request):
    """List all past import batches ordered most-recent first."""
    qs = ImportBatch.objects.order_by('-import_date', '-imported_at')
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'sales/import/history.html', {
        'page_obj': page_obj,
        'total_count': paginator.count,
    })
