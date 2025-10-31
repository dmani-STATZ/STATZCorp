from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404
import json

from ..models import (
    Contract, Clin, ClinType, Supplier, Nsn, SpecialPaymentTerms, Buyer, IdiqContract
)

@login_required
@require_http_methods(["GET"])
def get_select_options(request, field_name):
    """
    Generic view to get select options for various fields.
    Supports pagination and search.
    """
    search_term = request.GET.get('search', '')
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 10))
    specific_contract_id = request.GET.get('contract_id')
    
    offset = (page - 1) * page_size
    limit = page_size
    
    options = []
    total_count = 0
    
    try:
        if field_name == 'idiq':
            # IDIQ Contract search
            queryset = IdiqContract.objects.filter(closed=False)
            if search_term:
                queryset = queryset.filter(
                    Q(contract_number__icontains=search_term) |
                    Q(tab_num__icontains=search_term)
                ).order_by('contract_number')
            
            total_count = queryset.count()
            queryset = queryset[offset:offset+limit]
            
            for item in queryset:
                options.append({
                    'value': item.id,
                    'label': f"{item.contract_number or 'Unknown'}",
                    'tab_num': item.tab_num
                })

        elif field_name == 'contract':
            # Existing contract search logic
            queryset = Contract.objects.filter(company=request.active_company)
            
            if search_term:
                queryset = queryset.filter(
                    Q(contract_number__icontains=search_term) |
                    Q(po_number__icontains=search_term)
                ).order_by('-award_date')
            
            if specific_contract_id:
                try:
                    specific_contract = Contract.objects.get(id=specific_contract_id, company=request.active_company)
                    # Add the specific contract to the start of the list
                    options.append({
                        'value': specific_contract.id,
                        'label': f"{specific_contract.contract_number or 'Unknown'}"
                    })
                except Contract.DoesNotExist:
                    pass
            
            try:
                # Apply pagination
                total_count = len(queryset) if isinstance(queryset, list) else queryset.count()
                
                # If queryset is already a list (because we added a specific contract)
                if isinstance(queryset, list):
                    queryset = queryset[offset:offset+limit]
                else:
                    queryset = queryset[offset:offset+limit]
                
                for item in queryset:
                    options.append({
                        'value': item.id,
                        'label': f"{item.contract_number or 'Unknown'}"
                    })
            except Exception as e:
                print(f"Error processing contract results: {str(e)}")
                # If there was an error but we have a specific contract ID, try to include just that
                if specific_contract_id:
                    try:
                        specific_contract = Contract.objects.get(id=specific_contract_id, company=request.active_company)
                        options.append({
                            'value': specific_contract.id,
                            'label': f"{specific_contract.contract_number or 'Unknown'}"
                        })
                        total_count = 1
                    except Exception as inner_e:
                        print(f"Error getting specific contract as fallback: {str(inner_e)}")
                        total_count = 0
                else:
                    total_count = 0
                    
        elif field_name == 'buyer':
            # Get buyers, ordered by description
            queryset = Buyer.objects.all().order_by('description')
            
            # Apply search if provided
            if search_term:
                queryset = queryset.filter(description__icontains=search_term)
            
            # Get paginated results
            total = queryset.count()
            buyers = queryset[offset:offset + limit]
            
            # Format the results
            options = [{'value': buyer.id, 'label': buyer.description} for buyer in buyers]
            
            return JsonResponse({
                'success': True,
                'options': options,
                'total': total,
                'has_more': (offset + limit) < total
            })
        elif field_name == 'clin_type':
            # Get CLIN types
            queryset = ClinType.objects.all().order_by('description')
            
            # Apply search if provided
            if search_term:
                queryset = queryset.filter(description__icontains=search_term)
            
            # Check if we need to include a specific clin_type
            if specific_contract_id:
                try:
                    specific_clin_type = ClinType.objects.get(id=specific_contract_id)
                    # Make sure this specific clin_type is included in the results
                    if not queryset.filter(id=specific_contract_id).exists():
                        # Create a new queryset with the specific item first
                        queryset = list(queryset)
                        queryset.insert(0, specific_clin_type)
                except Exception as e:
                    print(f"Error getting specific clin_type: {str(e)}")
            
            # Apply pagination
            if isinstance(queryset, list):
                total_count = len(queryset)
                queryset = queryset[offset:offset+limit]
            else:
                total_count = queryset.count()
                queryset = queryset[offset:offset+limit]
            
            for item in queryset:
                options.append({
                    'value': item.id,
                    'label': f"{item.description or 'Unknown'}"
                })
                
        elif field_name == 'supplier':
            # Get suppliers, ordered by name
            queryset = Supplier.objects.all().order_by('name')
            
            # Apply search if provided
            if search_term:
                queryset = queryset.filter(
                    Q(name__icontains=search_term) | 
                    Q(cage_code__icontains=search_term)
                )
            
            # Get total count for pagination
            total_count = queryset.count()
            total_pages = (total_count + page_size - 1) // page_size
            
            # Apply pagination
            queryset = queryset[offset:offset+limit]
            
            # Format options
            for item in queryset:
                options.append({
                    'value': item.id,
                    'label': f"{item.name or 'Unknown'} ({item.cage_code or 'No CAGE'})"
                })
            
            return JsonResponse({
                'success': True,
                'options': options,
                'pagination': {
                    'total_pages': total_pages,
                    'current_page': page,
                    'total_count': total_count,
                    'page_size': page_size
                }
            })
                
        elif field_name == 'nsn':
            # Use the NsnView model for better performance
            queryset = Nsn.objects.all().order_by('nsn_code')
            
            # Apply search if provided
            if search_term:
                queryset = queryset.filter(
                    Q(nsn_code__icontains=search_term) | 
                    Q(description__icontains=search_term)
                )
            
            # Get total count for pagination
            total_count = queryset.count()
            total_pages = (total_count + page_size - 1) // page_size
            
            # Apply pagination
            queryset = queryset[offset:offset+limit]
            
            # Format options
            for item in queryset:
                options.append({
                    'value': item.id,
                    'label': f"{item.nsn_code or 'Unknown'} - {item.description or 'No description'}"
                })
            
            return JsonResponse({
                'success': True,
                'options': options,
                'pagination': {
                    'total_pages': total_pages,
                    'current_page': page,
                    'total_count': total_count,
                    'page_size': page_size
                }
            })
        
        elif field_name == 'special_payment_terms':
            # Get special payment terms
            queryset = SpecialPaymentTerms.objects.all().order_by('terms')
            
            # Apply search if provided
            if search_term:
                queryset = queryset.filter(terms__icontains=search_term)
            
            # Check if we need to include a specific payment term
            if specific_contract_id:
                try:
                    specific_term = SpecialPaymentTerms.objects.get(id=specific_contract_id)
                    # Make sure this specific term is included in the results
                    if not queryset.filter(id=specific_contract_id).exists():
                        # Create a new queryset with the specific item first
                        queryset = list(queryset)
                        queryset.insert(0, specific_term)
                except Exception as e:
                    print(f"Error getting specific payment term: {str(e)}")
            
            # Apply pagination
            if isinstance(queryset, list):
                total_count = len(queryset)
                queryset = queryset[offset:offset+limit]
            else:
                total_count = queryset.count()
                queryset = queryset[offset:offset+limit]
            
            for item in queryset:
                options.append({
                    'value': item.id,
                    'label': f"{item.terms or 'Unknown'}"
                })
        
        return JsonResponse({
            'success': True,
            'options': options,
            'total': total_count,
            'has_more': total_count > (offset + limit)
        })
        
    except Exception as e:
        print(f"Error in get_select_options: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'options': [],
            'pagination': {
                'total_pages': 1,
                'current_page': 1,
                'total_count': 0,
                'page_size': page_size
            }
        })

@login_required
@require_http_methods(["POST"])
def update_clin_field(request, clin_id):
    """API endpoint to update a single CLIN field"""
    try:
        clin = get_object_or_404(Clin, id=clin_id, company=request.active_company)
        data = json.loads(request.body)
        
        field = data.get('field')
        value = data.get('value')
        
        if field not in ['special_payment_terms', 'special_payment_terms_party']: # Need to move planned split to contract
            return JsonResponse({
                'success': False,
                'error': 'Invalid field'
            }, status=400)
        
        if field == 'special_payment_terms':
            if value:
                try:
                    special_payment_terms = SpecialPaymentTerms.objects.get(id=value)
                    clin.special_payment_terms = special_payment_terms
                except SpecialPaymentTerms.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'error': 'Invalid special payment terms'
                    }, status=400)
            else:
                clin.special_payment_terms = None
        else:
            setattr(clin, field, value)
        
        clin.modified_by = request.user
        clin.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully updated {field}'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_http_methods(["POST"])
def create_nsn(request):
    """
    API endpoint to create a new NSN record.
    Expects JSON data with:
    - nsn: NSN code
    - description: NSN description
    """
    try:
        data = json.loads(request.body)
        nsn_code = data.get('nsn')
        description = data.get('description')

        if not nsn_code:
            return JsonResponse({
                'success': False,
                'error': 'NSN code is required'
            }, status=400)

        # Check if NSN already exists
        if Nsn.objects.filter(nsn_code=nsn_code).exists():
            return JsonResponse({
                'success': False,
                'error': 'NSN code already exists'
            }, status=400)

        # Create new NSN record
        nsn = Nsn.objects.create(
            nsn_code=nsn_code,
            description=description,
            created_by=request.user,
            modified_by=request.user
        )

        return JsonResponse({
            'success': True,
            'id': nsn.id,
            'nsn_code': nsn.nsn_code,
            'description': nsn.description
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500) 


@login_required
@require_http_methods(["POST"])
def create_buyer(request):
    """
    API endpoint to create a new Buyer record.
    Expects JSON data with:
    - buyer_text: buyer name/description
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {
                'success': False,
                'error': 'Invalid JSON data',
            },
            status=400,
        )

    buyer_text = (data.get('buyer_text') or '').strip()

    if not buyer_text:
        return JsonResponse(
            {
                'success': False,
                'error': 'Buyer name is required',
            },
            status=400,
        )

    # Re-use existing Buyers when the description matches (case-insensitive)
    existing_buyer = Buyer.objects.filter(description__iexact=buyer_text).first()
    if existing_buyer:
        return JsonResponse(
            {
                'success': True,
                'id': existing_buyer.id,
                'description': existing_buyer.description,
                'duplicate': True,
                'message': 'Buyer already exists; using the existing record.',
            }
        )

    try:
        buyer = Buyer.objects.create(description=buyer_text)
    except Exception as exc:
        return JsonResponse(
            {
                'success': False,
                'error': str(exc),
            },
            status=500,
        )

    return JsonResponse(
        {
            'success': True,
            'id': buyer.id,
            'description': buyer.description,
        }
    )


@login_required
@require_http_methods(["POST"])
def create_supplier(request):
    """
    API endpoint to create a new Supplier record.
    Expects JSON data with:
    - name: supplier name (required)
    - cage_code: supplier CAGE code (required)
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {
                'success': False,
                'error': 'Invalid JSON data',
            },
            status=400,
        )

    name = (data.get('name') or '').strip()
    cage_code = (data.get('cage_code') or '').strip()

    if not name or not cage_code:
        return JsonResponse(
            {
                'success': False,
                'error': 'Supplier name and CAGE code are required',
            },
            status=400,
        )

    existing_supplier = Supplier.objects.filter(
        cage_code__iexact=cage_code
    ).first()
    if existing_supplier:
        return JsonResponse(
            {
                'success': True,
                'id': existing_supplier.id,
                'supplier_id': existing_supplier.id,
                'name': existing_supplier.name,
                'duplicate': True,
                'message': 'Supplier with this CAGE code already exists.',
            }
        )

    supplier = Supplier(
        name=name,
        cage_code=cage_code.upper(),
        created_by=request.user,
        modified_by=request.user,
    )

    try:
        supplier.save()
    except Exception as exc:
        return JsonResponse(
            {
                'success': False,
                'error': str(exc),
            },
            status=500,
        )

    return JsonResponse(
        {
            'success': True,
            'id': supplier.id,
            'supplier_id': supplier.id,
            'name': supplier.name,
            'cage_code': supplier.cage_code,
        }
    )


@login_required
@require_http_methods(["GET"])
def contract_day_counts(request):
    """
    Per-day counts of contracts in a date range:
    - awards: count of contracts with award_date == day
    - dues: count of contracts with due_date == day
    Params: start=YYYY-MM-DD, end=YYYY-MM-DD (inclusive)
    """
    start = request.GET.get('start')
    end = request.GET.get('end')
    from datetime import datetime
    if not start or not end:
        return JsonResponse({'error': 'start and end are required'}, status=400)
    try:
        start_date = datetime.fromisoformat(start[:10]).date()
        end_date = datetime.fromisoformat(end[:10]).date()
    except Exception:
        return JsonResponse({'error': 'Invalid date format'}, status=400)
    if end_date < start_date:
        return JsonResponse({'error': 'end must be after start'}, status=400)

    awards = (
        Contract.objects
        .filter(award_date__date__gte=start_date, award_date__date__lte=end_date)
        .values('award_date__date')
        .annotate(c=Count('id'))
    )
    dues = (
        Contract.objects
        .filter(due_date__date__gte=start_date, due_date__date__lte=end_date)
        .values('due_date__date')
        .annotate(c=Count('id'))
    )

    result = {}
    for row in awards:
        key = row['award_date__date'].isoformat()
        result.setdefault(key, {'awards': 0, 'dues': 0})
        result[key]['awards'] = row['c']
    for row in dues:
        key = row['due_date__date'].isoformat()
        result.setdefault(key, {'awards': 0, 'dues': 0})
        result[key]['dues'] = row['c']

    return JsonResponse({'counts': result})
