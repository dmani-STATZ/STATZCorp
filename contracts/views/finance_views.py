from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.views.generic import DetailView, ListView
from django.utils.decorators import method_decorator
from django.contrib import messages
from ..models import Contract, Clin, PaymentHistory, SpecialPaymentTerms
import json
import logging
from decimal import Decimal
from django.utils import timezone

logger = logging.getLogger(__name__)

def safe_float(value):
    """Convert a value to float, returning 0.0 if the value is None."""
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError) as e:
        logger.warning(f"Error converting value to float: {value}, Error: {str(e)}")
        return 0.0

@method_decorator(login_required, name='dispatch')
@method_decorator(ensure_csrf_cookie, name='dispatch')
class FinanceAuditView(DetailView):
    model = Contract
    template_name = 'contracts/finance_audit.html'
    context_object_name = 'contract'

    def get_object(self, queryset=None):
        if self.kwargs.get('pk'):
            return get_object_or_404(
                Contract.objects.select_related('buyer', 'contract_type', 'status', 'idiq_contract', 'company'),
                pk=self.kwargs['pk']
            )
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        try:
            if self.object:
                # Get CLINs for the contract
                context['clins'] = Clin.objects.filter(
                    contract=self.object
                ).select_related(
                    'supplier',
                    'special_payment_terms',
                    'nsn'
                ).order_by('item_number')
                
                # Get payment terms for dropdowns
                payment_terms = SpecialPaymentTerms.objects.all()
                context['payment_terms'] = payment_terms
                
                # Get Net Terms ID
                net_terms = payment_terms.filter(terms__icontains='net').first()
                context['net_terms_id'] = net_terms.id if net_terms else None
            
            # Add search query to context if it exists
            context['search_query'] = self.request.GET.get('q', '')
            
        except Exception as e:
            logger.error(f"Error in FinanceAuditView: {str(e)}")
            messages.error(self.request, 'An error occurred while loading the page.')
        
        return context

@method_decorator(login_required, name='dispatch')
class PaymentHistoryView(DetailView):
    model = Clin
    
    def get(self, request, *args, **kwargs):
        try:
            clin = self.get_object()
            payment_type = kwargs.get('payment_type')
            
            # Get payment history based on payment type
            history = []  # You'll need to implement the actual history retrieval logic
            
            return JsonResponse({
                'success': True,
                'history': history
            })
        except Clin.DoesNotExist:
            return JsonResponse({
                'error': 'CLIN not found'
            }, status=404)
        except Exception as e:
            logger.error(f"Error fetching payment history: {str(e)}")
            return JsonResponse({
                'error': 'Failed to fetch payment history'
            }, status=500)

@login_required
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def payment_history_api(request, clin_id, payment_type):
    """API endpoint for fetching and saving payment history"""
    try:
        clin = get_object_or_404(Clin, id=clin_id)
        
        if request.method == "GET":
            # Fetch payment history
            history = PaymentHistory.objects.filter(
                clin=clin,
                payment_type=payment_type
            ).order_by('-payment_date')
            
            history_data = [{
                'payment_date': entry.payment_date.strftime('%Y-%m-%d'),
                'payment_amount': str(entry.payment_amount),
                'payment_info': entry.payment_info or ''
            } for entry in history]
            
            # Calculate total
            total = sum(entry.payment_amount for entry in history)
            
            return JsonResponse({
                'success': True,
                'history': history_data,
                'total': str(total)
            })
        
        elif request.method == "POST":
            try:
                # Log the incoming request data for debugging
                logger.debug(f"Received payment history POST data: {request.body}")
                
                data = json.loads(request.body)
                logger.debug(f"Parsed JSON data: {data}")
                
                # Validate required fields
                required_fields = ['payment_amount', 'payment_date']
                if not all(key in data for key in required_fields):
                    missing_fields = [field for field in required_fields if field not in data]
                    return JsonResponse({
                        'success': False,
                        'error': f'Missing required fields: {", ".join(missing_fields)}'
                    }, status=400)
                
                # Create new payment history entry
                new_entry = PaymentHistory.objects.create(
                    clin=clin,
                    payment_type=payment_type,
                    payment_amount=Decimal(str(data['payment_amount'])),
                    payment_date=data['payment_date'],
                    payment_info=data.get('payment_info', ''),
                    created_by=request.user
                )
                logger.debug(f"Created new payment history entry: {new_entry.id}")
                
                # Update the corresponding field in the CLIN model
                total = PaymentHistory.objects.filter(
                    clin=clin,
                    payment_type=payment_type
                ).aggregate(total=models.Sum('payment_amount'))['total'] or Decimal('0')
                
                # Update the corresponding field based on payment_type
                if hasattr(clin, payment_type):
                    setattr(clin, payment_type, total)
                    clin.save(update_fields=[payment_type])
                    logger.debug(f"Updated CLIN {clin.id} {payment_type} to {total}")
                
                return JsonResponse({
                    'success': True,
                    'new_total': str(total),
                    'message': 'Payment history entry added successfully'
                })
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {str(e)}, Request body: {request.body}")
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid JSON format in request'
                }, status=400)
            except (ValueError, TypeError) as e:
                logger.error(f"Value/Type error: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'error': f'Invalid data format: {str(e)}'
                }, status=400)
            except Exception as e:
                logger.error(f"Unexpected error in payment history POST: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                }, status=400)
    except Exception as e:
        logger.error(f"Unexpected error in payment_history_api: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500) 