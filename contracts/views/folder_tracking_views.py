from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db.models import Q
from django.template.loader import render_to_string
from ..models import FolderTracking, Contract
from ..forms import FolderTrackingForm, ContractSearchForm
import json
import csv
from datetime import datetime

@login_required
def folder_tracking(request):
    # Get all non-closed records
    folders = FolderTracking.objects.filter(closed=False).order_by('stack', 'contract__contract_number')
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        folders = folders.filter(
            Q(contract__contract_number__icontains=search_query) |
            Q(contract__po_number__icontains=search_query) |
            Q(partial__icontains=search_query) |
            Q(tracking_number__icontains=search_query)
        )

    # Pagination
    paginator = Paginator(folders, 50)  # Show 50 items per page
    page = request.GET.get('page')
    folders = paginator.get_page(page)

    context = {
        'folders': folders,
        'search_form': ContractSearchForm(),
        'search_query': search_query,
    }
    return render(request, 'contracts/folder_tracking.html', context)

@login_required
def search_contracts(request):
    search_query = request.GET.get('q', '')
    search_performed = bool(search_query)
    contracts = []
    
    if search_query:
        contracts = Contract.objects.filter(
            Q(contract_number__icontains=search_query) |
            Q(po_number__icontains=search_query),
            open=True
        ).order_by('contract_number')[:10]  # Limit to 10 results for performance
    
    context = {
        'contracts': contracts,
        'search_performed': search_performed,
    }
    
    # Return direct HTML instead of JSON
    return render(request, 'contracts/includes/contract_search_results.html', context)

@login_required
def add_folder_tracking(request):
    if request.method == 'POST':
        contract_id = request.POST.get('contract')
        contract = get_object_or_404(Contract, id=contract_id)
        
        # Check if a folder already exists for this contract
        if FolderTracking.objects.filter(contract=contract, closed=False).exists():
            return JsonResponse({
                'status': 'error',
                'message': 'A folder already exists for this contract'
            })
        
        # Create new folder with default values
        folder = FolderTracking.objects.create(
            contract=contract,
            stack='1 - COS',  # Default to first stack
            added_by=request.user
        )
        return JsonResponse({'status': 'success'})
        
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})

@login_required
def close_folder_tracking(request, pk):
    folder = get_object_or_404(FolderTracking, pk=pk)
    folder.close_record(request.user)
    return JsonResponse({'status': 'success'})

@login_required
def toggle_highlight(request, pk):
    folder = get_object_or_404(FolderTracking, pk=pk)
    folder.toggle_highlight()
    return JsonResponse({'status': 'success', 'highlighted': folder.highlight})

@login_required
def export_folder_tracking(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="folder_tracking_{datetime.now().strftime("%Y%m%d")}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Stack', 'Contract', 'PO', 'Partial', 'RTS Email', 'QB INV', 'WAWF', 'WAWF QAR',
                    'VSM SCN', 'SIR SCN', 'Tracking', 'Tracking #', 'Sort Data', 'Note'])

    folders = FolderTracking.objects.filter(closed=False).order_by('stack', 'contract__contract_number')
    
    for folder in folders:
        writer.writerow([
            folder.stack,
            folder.contract.contract_number,
            folder.contract.po_number,
            folder.partial,
            'Yes' if folder.rts_email else 'No',
            folder.qb_inv,
            'Yes' if folder.wawf else 'No',
            'Yes' if folder.wawf_qar else 'No',
            folder.vsm_scn,
            folder.sir_scn,
            folder.tracking,
            folder.tracking_number,
            folder.sort_data,
            folder.note
        ])

    return response 