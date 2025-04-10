from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from processing.models import ProcessContract, ProcessClin
from contracts.models import Buyer, Nsn, Supplier

def match_buyer(request, pk):
    process_contract = get_object_or_404(ProcessContract, id=pk)
    buyer_text = request.POST.get('buyer_text', '')
    
    # Search for matching buyer
    buyers = Buyer.objects.filter(name__icontains=buyer_text)
    
    if buyers.exists():
        return JsonResponse({
            'success': True,
            'buyers': [{'id': b.id, 'name': b.name} for b in buyers]
        })
    return JsonResponse({'success': False, 'message': 'No matching buyers found'})

def match_nsn(request, pk, clin_id):
    process_clin = get_object_or_404(ProcessClin, id=clin_id)
    nsn_text = request.POST.get('nsn_text', '')
    
    # Search for matching NSN
    nsns = Nsn.objects.filter(nsn__icontains=nsn_text)
    
    if nsns.exists():
        return JsonResponse({
            'success': True,
            'nsns': [{'id': n.id, 'nsn': n.nsn, 'description': n.description} for n in nsns]
        })
    return JsonResponse({'success': False, 'message': 'No matching NSNs found'})

def match_supplier(request, pk, clin_id):
    process_clin = get_object_or_404(ProcessClin, id=clin_id)
    supplier_text = request.POST.get('supplier_text', '')
    
    # Search for matching supplier
    suppliers = Supplier.objects.filter(name__icontains=supplier_text)
    
    if suppliers.exists():
        return JsonResponse({
            'success': True,
            'suppliers': [{'id': s.id, 'name': s.name} for s in suppliers]
        })
    return JsonResponse({'success': False, 'message': 'No matching suppliers found'}) 