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
            
            # Apply search if provided
            if search_term:
                queryset = queryset.filter(contract_number__icontains=search_term)
            
            # Apply pagination
            total_count = queryset.count()
            queryset = queryset[offset:offset+limit]
            
            for item in queryset:
                options.append({
                    'value': item.id,
                    'label': f"{item.contract_number or 'Unknown'}"
                })
                
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
                    'label': f"{item.name or 'Unknown'} - {item.cage_code or 'No CAGE'}"
                })
                
        elif field_name == 'nsn':
            # Try to use the optimized NsnView model first
            try:
                # Use the materialized view for better performance
                if search_term:
                    # Use simple LIKE for searching since full-text search is not available
                    queryset = NsnView.objects.filter(
                        Q(nsn_code__contains=search_term) |
                        Q(search_vector__contains=search_term)
                    ).order_by('nsn_code')
                else:
                    queryset = NsnView.objects.all().order_by('nsn_code')
                
                # Apply pagination
                total_count = queryset.count()
                queryset = queryset[offset:offset+limit]
                
                for item in queryset:
                    options.append({
                        'value': item.id,
                        'label': f"{item.nsn_code or 'Unknown'} - {item.description or 'No description'}"
                    })
            except Exception as e:
                # Fall back to the regular Nsn model if the view is not available
                print(f"Error using NsnView, falling back to Nsn model: {str(e)}")
                
                # Get NSNs, ordered by code
                queryset = Nsn.objects.all()
                
                # Apply search if provided - this is critical for NSN performance
                if search_term:
                    queryset = queryset.filter(
                        Q(nsn_code__icontains=search_term) | 
                        Q(description__icontains=search_term) |
                        Q(part_number__icontains=search_term)
                    )
                    # Use order_by to prioritize exact matches
                    queryset = queryset.order_by(
                        '-nsn_code__istartswith',  # Prioritize codes that start with the search term
                        'nsn_code'                 # Then sort alphabetically
                    )
                else:
                    queryset = queryset.order_by('nsn_code')
                
                # Apply pagination
                total_count = queryset.count()
                queryset = queryset[offset:offset+limit]
                
                for item in queryset:
                    options.append({
                        'value': item.id,
                        'label': f"{item.nsn_code or 'Unknown'} - {item.description or 'No description'}"
                    })
                
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