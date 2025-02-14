from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from inventory.forms import InventoryItemForm
from inventory.models import InventoryItem
from django.http import JsonResponse


def autocomplete_nsn(request):
    if 'term' in request.GET:
        qs = InventoryItem.objects.filter(nsn__icontains=request.GET.get('term'))
        nsns = list()
        for item in qs:
            nsns.append(item.nsn)
        return JsonResponse(nsns, safe=False)
    return JsonResponse([], safe=False)

def autocomplete_description(request):
    if 'term' in request.GET:
        qs = InventoryItem.objects.filter(description__icontains=request.GET.get('term'))
        descriptions = list()
        for item in qs:
            descriptions.append(item.description)
        return JsonResponse(descriptions, safe=False)
    return JsonResponse([], safe=False)

def autocomplete_manufacturer(request):
    if 'term' in request.GET:
        qs = InventoryItem.objects.filter(manufacturer__icontains=request.GET.get('term'))
        manufacturers = list()
        for item in qs:
            manufacturers.append(item.manufacturer)
        return JsonResponse(manufacturers, safe=False)
    return JsonResponse([], safe=False)


@login_required
def dashboard(request):
    items = InventoryItem.objects.all()
    total_inventory_value = sum((item.quantity * item.purchaseprice) for item in items)
    return render(request, 'inventory/dashboard.html', {'items': items, 'total_inventory_value': total_inventory_value}) 

@login_required
def add_item(request):
    if request.method == 'POST':
        form = InventoryItemForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('inventory:dashboard')
    else:
        form = InventoryItemForm()
    return render(request, 'inventory/item_form.html', {'form': form})

@login_required
def edit_item(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)
    if request.method == 'POST':
        form = InventoryItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            return redirect('inventory:dashboard')
    else:
        form = InventoryItemForm(instance=item)
    return render(request, 'inventory/item_form.html', {'form': form})

@login_required
def delete_item(request, item_id):
    if request.method == 'POST':
        try:
            item = InventoryItem.objects.get(pk=item_id)
            item.delete()
            return JsonResponse({'success': True})
        except InventoryItem.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Item not found'})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def delete_item_ajax(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)
    if request.method == 'POST':
        item.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False})