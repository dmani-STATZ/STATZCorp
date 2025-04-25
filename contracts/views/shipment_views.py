from django.views.decorators.csrf import csrf_exempt
import json
import logging
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404
from ..models import Clin, ClinShipment

logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["POST"])
def create_shipment(request):
    """Create a new shipment."""
    logger.info("Create shipment endpoint hit")
    logger.debug(f"Request body: {request.body}")
    
    try:
        data = json.loads(request.body)
        logger.debug(f"Parsed data: {data}")
        
        clin_id = data.get('clin_id')
        if not clin_id:
            logger.error("No CLIN ID provided")
            raise ValueError('CLIN ID is required')
            
        clin = get_object_or_404(Clin, id=clin_id)
        logger.debug(f"Found CLIN: {clin.id}")
        
        # Validate required fields
        if not data.get('ship_date'):
            logger.error("No ship date provided")
            raise ValueError('Ship date is required')
        
        if not data.get('ship_qty'):
            logger.error("No ship quantity provided")
            raise ValueError('Ship quantity is required')
            
        # Create new shipment
        shipment = ClinShipment.objects.create(
            clin=clin,
            ship_qty=float(data.get('ship_qty', 0.00)),
            uom=data.get('uom', clin.uom),  # Get UOM from data or default to what is in the CLIN
            ship_date=data.get('ship_date'),
            comments=data.get('comments', '')
        )
        
        logger.info(f"Successfully created shipment {shipment.id}")
        # Just return the ship_date as it was received since it's already in YYYY-MM-DD format
        return JsonResponse({
            'success': True,
            'shipment_id': shipment.id,
            'ship_date': data.get('ship_date')
        })
        
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)
    except TypeError as e:
        logger.error(f"Type error: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': f'Invalid data format: {str(e)}'
        }, status=400)
    except Exception as e:
        import traceback
        logger.error(f"Unexpected error: {str(e)}")
        logger.error(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def update_shipment(request, shipment_id):
    """Update an existing shipment."""
    try:
        data = json.loads(request.body)
        shipment = get_object_or_404(ClinShipment, id=shipment_id)
        
        # Update shipment fields
        if 'ship_qty' in data:
            shipment.ship_qty = float(data['ship_qty'])
        if 'uom' in data:
            shipment.uom = data['uom']
        if 'ship_date' in data:
            shipment.ship_date = data['ship_date']
        if 'comments' in data:
            shipment.comments = data['comments']
        
        shipment.save()
        
        return JsonResponse({
            'success': True
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@csrf_exempt
@require_http_methods(["POST"])
def delete_shipment(request, shipment_id):
    """Delete a shipment."""
    try:
        shipment = get_object_or_404(ClinShipment, id=shipment_id)
        shipment.delete()
        
        return JsonResponse({
            'success': True
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@require_http_methods(["GET"])
def get_shipment(request, clin_id, shipment_id):
    """Get a specific shipment's details."""
    try:
        shipment = get_object_or_404(ClinShipment, id=shipment_id, clin_id=clin_id)
        return JsonResponse({
            'success': True,
            'shipment': {
                'id': shipment.id,
                'ship_qty': shipment.ship_qty,
                'uom': shipment.uom,
                'ship_date': shipment.ship_date.isoformat() if shipment.ship_date else None,
                'comments': shipment.comments
            }
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

# Optional: View for loading shipments via AJAX
@require_http_methods(["GET"])
def get_clin_shipments(request, clin_id):
    """Get HTML for shipments section."""
    from django.template.loader import render_to_string
    
    clin = get_object_or_404(Clin, id=clin_id)
    html = render_to_string('contracts/partials/clin_shipments.html', {
        'clin': clin,
        'mode': request.GET.get('mode', 'detail')
    })
    
    return JsonResponse({
        'success': True,
        'html': html
    })
