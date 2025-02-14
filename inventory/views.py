from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from inventory.forms import InventoryItemForm
from inventory.models import InventoryItem
from django.http import JsonResponse


def autocomplete_nsn(request):
    term = request.GET.get('term', '')
    items = InventoryItem.objects.filter(nsn__icontains=term).values_list('nsn', flat=True).distinct()[:10]
    return JsonResponse(list(items), safe=False)

def autocomplete_description(request):
    term = request.GET.get('term', '')
    items = InventoryItem.objects.filter(description__icontains=term).values_list('description', flat=True).distinct()[:10]
    return JsonResponse(list(items), safe=False)

def autocomplete_manufacturer(request):
    term = request.GET.get('term', '')
    items = InventoryItem.objects.filter(manufacturer__icontains=term).values_list('manufacturer', flat=True).distinct()[:10]
    return JsonResponse(list(items), safe=False)


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
def delete_item(request, pk):
    if request.method == 'POST':
        item = get_object_or_404(InventoryItem, pk=pk)
        item.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False})

def delete_item_ajax(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)
    if request.method == 'POST':
        item.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False})