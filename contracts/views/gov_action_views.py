"""Views for Gov Actions and Log Fields (contract management)."""
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from STATZWeb.decorators import conditional_login_required
from ..models import Clin, GovAction, Contract
from ..forms import GovActionForm
from suppliers.models import Supplier


@conditional_login_required
@require_http_methods(["GET"])
def get_clin_details(request, clin_id):
    """Return CLIN detail fields for display in contract management (AJAX)."""
    try:
        active_company = getattr(request, 'active_company', None)
        if not active_company:
            return JsonResponse({'success': False, 'error': 'No company selected.'}, status=400)
        clin = get_object_or_404(Clin.objects.select_related('supplier', 'nsn', 'clin_type', 'special_payment_terms'), id=clin_id, company=active_company)
        return JsonResponse({
            'success': True,
            'id': clin.id,
            'item_number': clin.item_number or '—',
            'item_type': clin.get_item_type_display() if clin.item_type else '—',
            'clin_po_num': clin.clin_po_num or clin.po_number or '—',
            'tab_num': clin.tab_num or '—',
            'supplier_name': clin.supplier.name if clin.supplier else 'N/A',
            'supplier_id': clin.supplier_id or None,
            'nsn': ((f"{clin.nsn.nsn_code or ''}" + (f" ({clin.nsn.description})" if clin.nsn.description else "")).strip() or 'N/A') if clin.nsn else 'N/A',
            'nsn_id': clin.nsn_id if clin.nsn else None,
            'ia': clin.get_ia_display() if clin.ia else '—',
            'fob': clin.get_fob_display() if clin.fob else '—',
            'special_payment_terms': str(clin.special_payment_terms) if clin.special_payment_terms else '—',
            'special_payment_terms_paid': bool(clin.special_payment_terms_paid),
            'supplier_due_date': clin.supplier_due_date.strftime('%m/%d/%Y') if clin.supplier_due_date else 'N/A',
            'supplier_due_date_late': bool(clin.supplier_due_date_late),
            'order_qty': clin.order_qty if clin.order_qty is not None else '—',
            'uom': clin.uom or 'EA',
            'quoted_due_date': clin.supplier_due_date.strftime('%m/%d/%Y') if clin.supplier_due_date else (clin.due_date.strftime('%m/%d/%Y') if clin.due_date else 'N/A'),
            'due_date': clin.due_date.strftime('%m/%d/%Y') if clin.due_date else 'N/A',
            'ship_date': clin.ship_date.strftime('%m/%d/%Y') if clin.ship_date else '—',
            'ship_qty': clin.ship_qty if clin.ship_qty is not None else '—',
            'item_value': str(clin.item_value) if clin.item_value is not None else '—',
            'unit_price': str(clin.unit_price) if clin.unit_price is not None else '—',
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def _format_address(addr):
    """Format Address model to dict for JSON."""
    if not addr:
        return None
    return {
        'address_line_1': addr.address_line_1 or '',
        'address_line_2': addr.address_line_2 or '',
        'city': addr.city or '',
        'state': addr.state or '',
        'zip': addr.zip or '',
        'display': str(addr).strip() or '—',
    }


@conditional_login_required
@require_http_methods(["GET"])
def get_supplier_info(request, supplier_id):
    """Return supplier details for Supplier Info modal (AJAX)."""
    try:
        supplier = get_object_or_404(
            Supplier.objects.select_related('contact', 'physical_address', 'billing_address', 'shipping_address'),
            id=supplier_id
        )
        contact = supplier.contact
        return JsonResponse({
            'success': True,
            'name': supplier.name or '—',
            'cage_code': supplier.cage_code or '—',
            'contact_name': f"{contact.name}" if contact else '—',
            'contact_email': (contact.email or supplier.primary_email or supplier.business_email) or '—',
            'contact_phone': (contact.phone or supplier.primary_phone or supplier.business_phone) or '—',
            'physical_address': _format_address(supplier.physical_address),
            'billing_address': _format_address(supplier.billing_address),
            'shipping_address': _format_address(supplier.shipping_address),
            'notes': supplier.notes or '—',
            'probation': bool(supplier.probation),
            'conditional': bool(supplier.conditional),
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@conditional_login_required
@require_http_methods(["GET"])
def get_clin_log_fields(request, clin_id):
    """Return log_status and log_notes for a CLIN (AJAX)."""
    try:
        active_company = getattr(request, 'active_company', None)
        if not active_company:
            return JsonResponse({'success': False, 'error': 'No company selected.'}, status=400)
        clin = get_object_or_404(Clin, id=clin_id, company=active_company)
        return JsonResponse({
            'success': True,
            'log_status': clin.log_status or '',
            'log_notes': clin.log_notes or '',
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@conditional_login_required
@require_http_methods(["POST"])
def save_clin_log_fields(request, clin_id):
    """Save log_status and log_notes for a CLIN (AJAX)."""
    try:
        active_company = getattr(request, 'active_company', None)
        if not active_company:
            return JsonResponse({'success': False, 'error': 'No company selected.'}, status=400)
        clin = get_object_or_404(Clin, id=clin_id, company=active_company)
        import json
        data = json.loads(request.body) if request.body else {}
        clin.log_status = data.get('log_status', '')
        clin.log_notes = data.get('log_notes', '')
        clin.modified_by = request.user
        clin.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@conditional_login_required
@require_http_methods(["POST"])
def gov_action_create(request, contract_id):
    """Create a new Gov Action for a contract (AJAX)."""
    try:
        active_company = getattr(request, 'active_company', None)
        if not active_company:
            return JsonResponse({'success': False, 'error': 'No company selected.'}, status=400)
        contract = get_object_or_404(Contract, id=contract_id, company=active_company)
        form = GovActionForm(request.POST)
        if form.is_valid():
            gov_action = form.save(commit=False)
            gov_action.contract = contract
            gov_action.company = active_company
            gov_action.created_by = request.user
            gov_action.modified_by = request.user
            gov_action.save()
            return JsonResponse({
                'success': True,
                'id': gov_action.id,
                'action': gov_action.get_action_display() or gov_action.action or '',
                'number': gov_action.number or '',
                'request': gov_action.get_request_display() or gov_action.request or '',
                'date_submitted': gov_action.date_submitted.strftime('%Y-%m-%d') if gov_action.date_submitted else '',
                'date_closed': gov_action.date_closed.strftime('%Y-%m-%d') if gov_action.date_closed else '',
                'initiated': gov_action.get_initiated_display() or gov_action.initiated or '',
            })
        return JsonResponse({'success': False, 'errors': form.errors}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@conditional_login_required
@require_http_methods(["POST"])
def gov_action_delete(request, pk):
    """Delete a Gov Action (AJAX)."""
    try:
        active_company = getattr(request, 'active_company', None)
        if not active_company:
            return JsonResponse({'success': False, 'error': 'No company selected.'}, status=400)
        gov_action = get_object_or_404(GovAction, pk=pk, company=active_company)
        gov_action.delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
