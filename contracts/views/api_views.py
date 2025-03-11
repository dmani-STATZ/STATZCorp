from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.db.models import Q

from ..models import (
    Contract, Clin, ClinType, Supplier, Nsn, SpecialPaymentTerms, NsnView
)

@login_required
@require_http_methods(["GET"])
def get_select_options(request, field_name):
    """
    API endpoint to get options for select fields asynchronously.
    This improves page load time by loading the foreign key data after the page loads.
    """
    options = []
    
    try:
        # Get pagination and search parameters
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        search_term = request.GET.get('search', '')
        include_id = request.GET.get('include_id')
        
        # Calculate offset and limit
        offset = (page - 1) * page_size
        limit = page_size
        
        if field_name == 'contract':
            # Get contracts, ordered by contract number
            queryset = Contract.objects.all().order_by('contract_number')
            
            # Apply search if provided
            if search_term:
                queryset = queryset.filter(contract_number__icontains=search_term)
            
            # Check if we need to include a specific contract
            specific_contract_id = include_id
            if specific_contract_id:
                try:
                    specific_contract = Contract.objects.get(id=specific_contract_id)
                    # Check if the contract is already in the queryset
                    if not queryset.filter(id=specific_contract_id).exists():
                        # If not, we'll add it to the results later
                        pass
                except Exception as e:
                    print(f"Error getting specific contract: {str(e)}")
            
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
                
        elif field_name == 'clin_type':
            # Get CLIN types
            queryset = ClinType.objects.all().order_by('description')
            
            # Apply search if provided
            if search_term:
                queryset = queryset.filter(description__icontains=search_term)
            
            # Check if we need to include a specific clin_type
            if include_id:
                try:
                    specific_clin_type = ClinType.objects.get(id=include_id)
                    # Make sure this specific clin_type is included in the results
                    if not queryset.filter(id=include_id).exists():
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
            if include_id:
                try:
                    specific_supplier = Supplier.objects.get(id=include_id)
                    # Make sure this specific supplier is included in the results
                    if not queryset.filter(id=include_id).exists():
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
            if include_id:
                try:
                    specific_nsn = Nsn.objects.get(id=include_id)
                    # Make sure this specific NSN is included in the results
                    if not queryset.filter(id=include_id).exists():
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
            if include_id:
                try:
                    specific_term = SpecialPaymentTerms.objects.get(id=include_id)
                    # Make sure this specific term is included in the results
                    if not queryset.filter(id=include_id).exists():
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
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_count': total_count,
                'total_pages': (total_count + page_size - 1) // page_size
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500) 