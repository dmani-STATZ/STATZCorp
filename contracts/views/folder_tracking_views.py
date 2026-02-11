from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db.models import Q
from django.template.loader import render_to_string
from ..models import FolderTracking, Contract, FolderStack
from users.models import UserSetting, UserSettingState
from ..forms import FolderTrackingForm, ContractSearchForm
import json
import csv
from datetime import datetime
from contracts.utils.excel_utils import Workbook, get_column_letter, PatternFill, Font, Alignment, Border, Side
import webcolors
from django.views.decorators.http import require_POST
from django.forms.models import model_to_dict
import re

def color_to_argb(color):
    """Convert color names or RGB values to ARGB hex format required by openpyxl"""
    try:
        # If it's a hex value
        if color.startswith('#'):
            color = color[1:]
            # Add alpha channel if not present
            if len(color) == 6:
                return 'FF' + color.upper()
            return color.upper()
        
        # Try to convert color name to hex
        rgb = webcolors.name_to_rgb(color.lower())
        hex_color = '%02x%02x%02x' % rgb
        return 'FF' + hex_color.upper()
    except (ValueError, AttributeError):
        # Return white if color is not recognized
        return 'FFFFFFFF'

def get_contrast_color(hex_color):
    """
    Calculate whether black or white text should be used based on background color.
    Using W3C recommended contrast calculation.
    """
    # Remove the hash if present
    hex_color = hex_color.lstrip('#')
    
    # Convert hex to RGB
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    except (ValueError, IndexError):
        return 'black'  # Default to black text if invalid hex
    
    # Calculate relative luminance
    # Using sRGB relative luminance calculation
    def get_luminance(value):
        value = value / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    
    r_luminance = get_luminance(r)
    g_luminance = get_luminance(g)
    b_luminance = get_luminance(b)
    
    # Calculate relative luminance using W3C formula
    luminance = 0.2126 * r_luminance + 0.7152 * g_luminance + 0.0722 * b_luminance
    
    # Return white for dark backgrounds (low luminance)
    return 'white' if luminance < 0.5 else 'black'

@login_required
def folder_tracking(request):
    # Get all non-closed records and sort by stack order
    folders = FolderTracking.objects.filter(closed=False).select_related(
        'contract', 'stack_id'
    ).order_by('stack_id__order', 'contract__contract_number')
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        folders = folders.filter(
            Q(contract__contract_number__icontains=search_query) |
            Q(contract__po_number__icontains=search_query) |
            Q(partial__icontains=search_query) |
            Q(tracking_number__icontains=search_query)
        )

    # Get or create the pagination setting
    pagination_setting, setting_created = UserSetting.objects.get_or_create(
        name='folder_tracking_pagination_disabled',
        defaults={
            'description': 'Controls whether pagination is disabled in the folder tracking view',
            'setting_type': 'boolean',
            'default_value': 'false',
            'is_global': False
        }
    )
    
    if setting_created:
        print(f"Created new pagination setting with default value: {pagination_setting.default_value}")

    # Get or create the user's setting state
    setting_state, state_created = UserSettingState.objects.get_or_create(
        user=request.user,
        setting=pagination_setting,
        defaults={'value': pagination_setting.default_value}
    )
    
    if state_created:
        print(f"Created new pagination state for user {request.user.username} with default value: {setting_state.get_value()}")

    # Handle toggle button click (POST request)
    if request.method == 'POST' and request.POST.get('toggle_pagination') == 'true':
        current_value = setting_state.get_value()
        new_value = not current_value
        setting_state.set_value(new_value)
        print(f"Toggled pagination setting for user {request.user.username} from {current_value} to {new_value}")
        return JsonResponse({
            'status': 'success',
            'pagination_disabled': new_value
        })

    # Get current pagination state
    pagination_disabled = setting_state.get_value()
    print(f"Current pagination state for user {request.user.username}: {pagination_disabled}")
    
    if pagination_disabled:
        # Return all records without pagination
        print(f"Pagination disabled - returning all {folders.count()} records")
    else:
        # Apply pagination
        paginator = Paginator(folders, 22)  # Show 22 items per page  (22 Items is the perfect size for the screen)
        page = request.GET.get('page')
        folders = paginator.get_page(page)
        print(f"Pagination enabled - returning page {page} with {len(folders)} records")

    # Get stack colors from FolderStack model
    stacks = FolderStack.objects.order_by('order')
    stack_colors = {
        stack.id: {
            'bg': stack.color,
            'text': get_contrast_color(stack.color)
        }
        for stack in stacks
    }

    context = {
        'folders': folders,
        'search_form': ContractSearchForm(),
        'search_query': search_query,
        'stack_colors': stack_colors,
        'stacks': stacks,
        'pagination_disabled': pagination_disabled,
    }
    return render(request, 'contracts/folder_tracking.html', context)

@login_required
def search_contracts(request):
    search_query = request.GET.get('q', '')
    status_filter = request.GET.get('status', 'open')  # open | closed | both
    search_performed = bool(search_query)
    contracts = []
    
    if search_query:
        qs = Contract.objects.filter(
            Q(contract_number__icontains=search_query) |
            Q(po_number__icontains=search_query)
        )
        # Company scope
        if getattr(request, 'active_company', None):
            qs = qs.filter(company=request.active_company)
        # Open / Closed / Both filter
        if status_filter == 'open':
            qs = qs.filter(status__description='Open')
        elif status_filter == 'closed':
            qs = qs.filter(status__description='Closed')
        elif status_filter == 'both':
            qs = qs.filter(status__description__in=['Open', 'Closed'])
        contracts = list(qs.order_by('contract_number')[:50])  # Increased limit with filter
    
    context = {
        'contracts': contracts,
        'search_performed': search_performed,
        'status_filter': status_filter,
    }
    
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
            stack='0 - NONE',  # Default to first stack
            added_by=request.user,
            created_by=request.user,
            modified_by=request.user
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
    folder.toggle_highlight(request.user)
    return JsonResponse({'status': 'success', 'highlighted': folder.highlight})

@login_required
def export_folder_tracking(request):
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="folder_tracking_{datetime.now().strftime("%Y%m%d")}.xlsx"'

    # Create workbook and select active sheet
    wb = Workbook()()  # Note the double parentheses: Workbook is now a function that returns the class
    ws = wb.active
    ws.title = "Folder Tracking"

    # Define headers
    headers = ['Stack', 'Contract', 'PO', 'Partial', 'RTS Email', 'QB INV', 'WAWF', 'WAWF QAR',
               'VSM SCN', 'SIR SCN', 'Tracking', 'Tracking #', 'Sort Data', 'Note']

    # Write headers with styling
    header_fill = PatternFill()(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    header_font = Font()(color="FFFFFF", bold=True)
    header_alignment = Alignment()(horizontal='center', vertical='center')
    
    # Initialize dictionary to track maximum width of each column
    max_lengths = {i: len(str(header)) for i, header in enumerate(headers)}
    
    # Apply styling to headers
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.value = header
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment

    # Get folders and sort them
    folders = FolderTracking.objects.filter(closed=False).extra(
        select={'stack_num': "CAST(SUBSTRING(stack, 1, CHARINDEX(' -', stack) - 1) AS INTEGER)"}
    ).order_by('stack_num', 'contract__contract_number')

    # Write data with styling
    thin_border = Border()(
        left=Side()(style='thin'),
        right=Side()(style='thin'),
        top=Side()(style='thin'),
        bottom=Side()(style='thin')
    )

    # Define boolean fields (these will be center-aligned)
    boolean_fields = {'RTS Email', 'WAWF', 'WAWF QAR'}

    for row_idx, folder in enumerate(folders, 2):
        # Get stack color
        stack_color = folder.stack_color
        if not stack_color:
            stack_color = 'FFFFFF'  # Default to white if no color specified
        
        # Convert color to ARGB format
        argb_color = color_to_argb(stack_color)
        
        # Create fill style for the stack column
        stack_fill = PatternFill()(start_color=argb_color, end_color=argb_color, fill_type="solid")

        # Write row data with styling
        row_data = [
            folder.stack,
            folder.contract.contract_number,
            folder.contract.po_number,
            folder.partial or '',
            'Yes' if folder.rts_email else 'No',
            folder.qb_inv or '',
            'Yes' if folder.wawf else 'No',
            'Yes' if folder.wawf_qar else 'No',
            folder.vsm_scn or '',
            folder.sir_scn or '',
            folder.tracking or '',
            folder.tracking_number or '',
            folder.sort_data or '',
            folder.note or ''
        ]

        # Update maximum lengths
        for i, value in enumerate(row_data):
            max_lengths[i] = max(max_lengths[i], len(str(value or '')))

        for col_idx, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            
            # Apply basic styling to all cells
            cell.border = thin_border
            cell.font = Font()(color="000000")  # Black text for all cells
            
            # Set alignment based on field type
            if headers[col_idx - 1] in boolean_fields:
                cell.alignment = Alignment()(horizontal='center', vertical='center')
            else:
                cell.alignment = Alignment()(horizontal='left', vertical='center')
            
            # Apply color only to stack column
            if col_idx == 1:  # Stack column
                cell.fill = stack_fill
            else:
                cell.fill = PatternFill()(start_color="FFFFFFFF", end_color="FFFFFFFF", fill_type="solid")  # White background
            
            # Apply highlight to non-stack columns if needed
            if folder.highlight and col_idx > 1:
                cell.fill = PatternFill()(start_color="FFFFFF00", end_color="FFFFFF00", fill_type="solid")  # ARGB yellow

    # Adjust column widths based on content
    for i, max_length in max_lengths.items():
        column = get_column_letter()(i + 1)  # Call as a function
        # Set width with some padding and maximum width limit
        adjusted_width = min(max_length + 2, 50)  # Add 2 for padding, cap at 50
        ws.column_dimensions[column].width = adjusted_width

    # Save workbook
    wb.save(response)
    return response

@login_required
def update_folder_field(request, pk):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'})
    
    folder = get_object_or_404(FolderTracking, pk=pk)
    field = request.POST.get('field')
    value = request.POST.get('value')
    
    if field not in ['stack_id', 'partial', 'rts_email', 'qb_inv', 'wawf', 'wawf_qar', 
                    'vsm_scn', 'sir_scn', 'tracking', 'tracking_number', 'note']:
        return JsonResponse({'status': 'error', 'message': 'Invalid field'})
    
    # Handle boolean fields
    if field in ['rts_email', 'wawf', 'wawf_qar']:
        value = value.lower() == 'true'
    
    # Handle stack_id field
    if field == 'stack_id':
        try:
            stack = FolderStack.objects.get(id=value)
            folder.stack_id = stack
            # Update the legacy stack field for backward compatibility
            folder.stack = f"{stack.order} - {stack.name}"
            response_data = {
                'status': 'success',
                'value': value
            }
            response_data.update({
                'color': stack.color,
                'text_color': get_contrast_color(stack.color)
            })
        except FolderStack.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Invalid stack'})
    else:
        setattr(folder, field, value)
    
    # Update audit fields
    folder.modified_by = request.user
    folder.save()
    
    return JsonResponse(response_data)

# --- FolderStack AJAX Endpoints ---
@login_required
def folderstack_list(request):
    stacks = FolderStack.objects.order_by('order', 'id')
    data = [
        {
            'id': stack.id,
            'name': stack.name,
            'color': stack.color,
            'order': stack.order,
        }
        for stack in stacks
    ]
    return JsonResponse({'stacks': data})

@login_required
@require_POST
def folderstack_save(request):
    data = json.loads(request.body)
    stacks = data.get('stacks', [])
    updated_ids = set()
    order_counter = 1
    for stack in stacks:
        stack_id = stack.get('id')
        name = stack.get('name', '').strip()
        color = stack.get('color', '#ffffff')
        if not name:
            continue
        if stack_id == 'new':
            FolderStack.objects.create(name=name, color=color, order=order_counter)
        else:
            try:
                fs = FolderStack.objects.get(id=stack_id)
                fs.name = name
                fs.color = color
                fs.order = order_counter
                fs.save()
                updated_ids.add(fs.id)
            except FolderStack.DoesNotExist:
                continue
        order_counter += 1
    # Remove stacks not in the list (optional, for full sync)
    # FolderStack.objects.exclude(id__in=updated_ids).delete()
    return JsonResponse({'status': 'success'})

@login_required
@require_POST
def folderstack_move(request, pk):
    direction = request.POST.get('direction')
    try:
        stack = FolderStack.objects.get(pk=pk)
    except FolderStack.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Stack not found'})
    all_stacks = list(FolderStack.objects.order_by('order', 'id'))
    idx = next((i for i, s in enumerate(all_stacks) if s.id == stack.id), None)
    if idx is None:
        return JsonResponse({'status': 'error', 'message': 'Stack not found in list'})
    if direction == 'up' and idx > 0:
        prev = all_stacks[idx-1]
        stack.order, prev.order = prev.order, stack.order
        stack.save()
        prev.save()
    elif direction == 'down' and idx < len(all_stacks)-1:
        nxt = all_stacks[idx+1]
        stack.order, nxt.order = nxt.order, stack.order
        stack.save()
        nxt.save()
    return JsonResponse({'status': 'success'})

@login_required
@require_POST
def folderstack_delete(request, pk):
    try:
        stack = FolderStack.objects.get(pk=pk)
        stack.delete()
        return JsonResponse({'status': 'success'})
    except FolderStack.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Stack not found'}) 