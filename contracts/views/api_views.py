from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.db.models import Q
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
            queryset = Contract.objects.all()
            
            if search_term:
                queryset = queryset.filter(
                    Q(contract_number__icontains=search_term) |
                    Q(po_number__icontains=search_term)
                ).order_by('-award_date')
            
            if specific_contract_id:
                try:
                    specific_contract = Contract.objects.get(id=specific_contract_id)
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
                        specific_contract = Contract.objects.get(id=specific_contract_id)
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
            
            # Check if we need to include a specific supplier
            if specific_contract_id:
                try:
                    specific_supplier = Supplier.objects.get(id=specific_contract_id)
                    # Make sure this specific supplier is included in the results
                    if not queryset.filter(id=specific_contract_id).exists():
                        # Create a new queryset with the specific item first
                        queryset = list(queryset)
                        queryset.insert(0, specific_supplier)
                except Exception as e:
                    print(f"Error getting specific supplier: {str(e)}")
            
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
                    'label': f"{item.name or 'Unknown'} ({item.cage_code or 'No CAGE'})"
                })
                
        elif field_name == 'nsn':
            # Use the NsnView model for better performance
            queryset = NsnView.objects.all().order_by('nsn_code')
            
            # Apply search if provided
            if search_term:
                queryset = queryset.filter(
                    Q(nsn_code__icontains=search_term) | 
                    Q(description__icontains=search_term)
                )
            
            # Check if we need to include a specific NSN
            if specific_contract_id:
                try:
                    specific_nsn = Nsn.objects.get(id=specific_contract_id)
                    # Make sure this specific NSN is included in the results
                    if not queryset.filter(id=specific_contract_id).exists():
                        # For NSN, we need to handle this differently since we're using NsnView
                        # We'll add the specific NSN to the options at the end
                        options.append({
                            'value': specific_nsn.id,
                            'label': f"{specific_nsn.nsn_code or 'Unknown'} - {specific_nsn.description or 'No description'}"
                        })
                except Exception as e:
                    print(f"Error getting specific NSN: {str(e)}")
            
            try:
                # Apply pagination
                total_count = queryset.count()
                queryset = queryset[offset:offset+limit]
                
                for item in queryset:
                    options.append({
                        'value': item.id,
                        'label': f"{item.nsn_code or 'Unknown'} - {item.description or 'No description'}"
                    })
            except Exception as e:
                print(f"Error processing NSN results: {str(e)}")
                # Return empty results on error
                total_count = 0
                
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
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@login_required
@require_http_methods(["POST"])
def update_clin_field(request, clin_id):
    """API endpoint to update a single CLIN field"""
    try:
        clin = get_object_or_404(Clin, id=clin_id)
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