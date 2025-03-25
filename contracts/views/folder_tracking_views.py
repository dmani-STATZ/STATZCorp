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
    # Get all non-closed records and sort by numeric stack value
    folders = FolderTracking.objects.filter(closed=False).extra(
        select={'stack_num': "CAST(SUBSTRING(stack, 1, CHARINDEX(' -', stack) - 1) AS INTEGER)"}
    ).order_by('stack_num', 'contract__contract_number')
    
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
    paginator = Paginator(folders, 25)  # Show 25 items per page
    page = request.GET.get('page')
    folders = paginator.get_page(page)

    # Get stack colors from model - simplified key format
    stack_colors = {}
    for key, value in FolderTracking.STACK_COLORS.items():
        # Extract the name part (e.g., 'NONE', 'COS', 'PAID', etc.)
        name = key.split(' - ')[1]
        stack_colors[name.lower()] = {
            'bg': value,
            'text': 'white' if value.lower() in ['blue', 'green', 'grey', 'teal', 'red'] else 'black'
        }

    context = {
        'folders': folders,
        'search_form': ContractSearchForm(),
        'search_query': search_query,
        'stack_colors': stack_colors,
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

@login_required
def update_folder_field(request, pk):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'})
    
    folder = get_object_or_404(FolderTracking, pk=pk)
    field = request.POST.get('field')
    value = request.POST.get('value')
    
    if field not in ['stack', 'partial', 'rts_email', 'qb_inv', 'wawf', 'wawf_qar', 
                    'vsm_scn', 'sir_scn', 'tracking', 'tracking_number', 'note']:
        return JsonResponse({'status': 'error', 'message': 'Invalid field'})
    
    # Handle boolean fields
    if field in ['rts_email', 'wawf', 'wawf_qar']:
        value = value.lower() == 'true'
    
    setattr(folder, field, value)
    folder.save()
    
    return JsonResponse({
        'status': 'success',
        'value': value if field not in ['rts_email', 'wawf', 'wawf_qar'] else bool(value)
    }) 