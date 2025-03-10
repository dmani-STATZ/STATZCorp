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
        
        # Calculate offset and limit
        offset = (page - 1) * page_size
        limit = page_size
        
        if field_name == 'contract':
            # Get contracts, ordered by contract number
            queryset = Contract.objects.filter(
                Q(open=True) | Q(open__isnull=True)
            ).order_by('contract_number')
            
            # Check if we need to include a specific contract by ID
            specific_contract_id = request.GET.get('include_id')
            
            # Apply search if provided
            if search_term:
                queryset = queryset.filter(contract_number__icontains=search_term)
            
            # If we have a specific ID to include (for editing existing records)
            if specific_contract_id:
                try:
                    # Try to get the specific contract even if it doesn't match other filters
                    specific_contract = Contract.objects.filter(id=specific_contract_id).first()
                    if specific_contract and specific_contract not in queryset:
                        # Add this contract to our results if it exists but wasn't included
                        # We'll prepend it to make sure it's included in the first page
                        queryset = list(queryset)
                        queryset.insert(0, specific_contract)
                except Exception as e:
                    print(f"Error including specific contract: {str(e)}")
            
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
            
            # Apply pagination
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
            
            # Apply pagination
            total_count = queryset.count()
            queryset = queryset[offset:offset+limit]
            
            for item in queryset:
                options.append({
                    'value': item.id,
                    'label': f"{item.name or 'Unknown'} ({item.cage_code or 'No CAGE'})"
                })
                
        elif field_name == 'nsn':
            # COMMENTED OUT: NSNView usage for performance testing
            # Try to use the optimized NsnView model first
            # try:
            #     # Use the materialized view for better performance
            #     if search_term:
            #         # Use simple LIKE for searching since full-text search is not available
            #         queryset = NsnView.objects.filter(
            #             Q(nsn_code__contains=search_term) |
            #             Q(search_vector__contains=search_term)
            #         ).order_by('nsn_code')
            #     else:
            #         queryset = NsnView.objects.all().order_by('nsn_code')
            #     
            #     # Apply pagination
            #     total_count = queryset.count()
            #     queryset = queryset[offset:offset+limit]
            #     
            #     for item in queryset:
            #         options.append({
            #             'value': item.id,
            #             'label': f"{item.nsn_code or 'Unknown'} - {item.description or 'No description'}"
            #         })
            # except Exception as e:
            #     # Fall back to the regular Nsn model if the view is not available
            #     print(f"Error using NsnView, falling back to Nsn model: {str(e)}")
                
            # USING ONLY: Regular Nsn model for testing
            # Get NSNs, ordered by code
            queryset = Nsn.objects.all()
            
            # Apply search if provided - this is critical for NSN performance
            if search_term:
                try:
                    # First try with istartswith for better performance
                    queryset = queryset.filter(
                        Q(nsn_code__istartswith=search_term) | 
                        Q(description__icontains=search_term) |
                        Q(part_number__icontains=search_term)
                    )
                    
                    # Check if we got any results
                    if queryset.count() == 0:
                        # If no results, try with a more permissive search
                        queryset = Nsn.objects.filter(
                            Q(nsn_code__icontains=search_term) | 
                            Q(description__icontains=search_term) |
                            Q(part_number__icontains=search_term)
                        )
                    
                    # Sort results
                    queryset = queryset.order_by('nsn_code')
                except Exception as e:
                    print(f"Error in NSN search: {str(e)}")
                    # Return empty queryset on error
                    queryset = Nsn.objects.none()
            else:
                # If no search term, just return first page ordered by code
                queryset = queryset.order_by('nsn_code')
            
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
            
            # Apply pagination
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