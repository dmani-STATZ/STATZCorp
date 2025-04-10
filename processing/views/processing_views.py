from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import DetailView, UpdateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.forms import inlineformset_factory
from processing.models import ProcessContract, ProcessCLIN, ContractQueue
from processing.forms import ProcessContractForm, ProcessCLINForm
from contracts.models import Contract, Clin, Buyer, Nsn, Supplier
import csv
import os
from django.conf import settings

def start_processing(request, queue_id):
    queue_item = get_object_or_404(ContractQueue, id=queue_id)
    
    # Create ProcessContract from queue item
    process_contract = ProcessContract.objects.create(
        contract_number=queue_item.contract_number,
        buyer_text=queue_item.buyer,
        award_date=queue_item.award_date,
        due_date=queue_item.due_date,
        contract_value=queue_item.contract_value,
        description=queue_item.description,
        queue_id=queue_id,
        created_by=request.user,
        modified_by=request.user
    )
    
    # Create ProcessCLINs from queue item
    for clin_data in queue_item.clins.all():
        ProcessCLIN.objects.create(
            process_contract=process_contract,
            clin_number=clin_data.clin_number,
            nsn_text=clin_data.nsn,
            nsn_description_text=clin_data.nsn_description,
            supplier_text=clin_data.supplier,
            quantity=clin_data.quantity,
            unit_price=clin_data.unit_price,
            total_price=clin_data.total_price,
            description=clin_data.description
        )
    
    # Update queue item status
    queue_item.status = 'processing'
    queue_item.save()
    
    messages.success(request, 'Contract processing started successfully.')
    return redirect('processing:process_contract_detail', pk=process_contract.id)

class ProcessContractDetailView(LoginRequiredMixin, DetailView):
    model = ProcessContract
    template_name = 'processing/process_contract_detail.html'
    context_object_name = 'contract'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['clins'] = self.object.clins.all()
        return context

class ProcessContractUpdateView(LoginRequiredMixin, UpdateView):
    model = ProcessContract
    form_class = ProcessContractForm
    template_name = 'processing/process_contract_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['clins'] = ProcessCLINFormSet(self.request.POST, instance=self.object)
        else:
            context['clins'] = ProcessCLINFormSet(instance=self.object)
        return context
    
    def form_valid(self, form):
        context = self.get_context_data()
        clins = context['clins']
        if clins.is_valid():
            self.object = form.save()
            clins.instance = self.object
            clins.save()
            return redirect('processing:process_contract_detail', pk=self.object.id)
        return self.render_to_response(self.get_context_data(form=form))

def finalize_contract(request, pk):
    process_contract = get_object_or_404(ProcessContract, id=pk)
    
    # Create final Contract
    contract = Contract.objects.create(
        contract_number=process_contract.contract_number,
        buyer=process_contract.buyer,
        award_date=process_contract.award_date,
        due_date=process_contract.due_date,
        contract_value=process_contract.contract_value,
        description=process_contract.description,
        created_by=request.user,
        modified_by=request.user
    )
    
    # Create final CLINs
    for process_clin in process_contract.clins.all():
        Clin.objects.create(
            contract=contract,
            clin_number=process_clin.clin_number,
            nsn=process_clin.nsn,
            supplier=process_clin.supplier,
            quantity=process_clin.quantity,
            unit_price=process_clin.unit_price,
            total_price=process_clin.total_price,
            description=process_clin.description
        )
    
    # Update queue item status
    queue_item = ContractQueue.objects.get(id=process_contract.queue_id)
    queue_item.status = 'completed'
    queue_item.save()
    
    # Delete processing records
    process_contract.delete()
    
    messages.success(request, 'Contract finalized successfully.')
    return redirect('contracts:contract_detail', pk=contract.id)

# Create formset for CLINs
ProcessCLINFormSet = inlineformset_factory(
    ProcessContract,
    ProcessCLIN,
    form=ProcessCLINForm,
    extra=1,
    can_delete=True
)

def download_csv_template(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="contract_template.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Contract Number',
        'Buyer',
        'Award Date',
        'Due Date',
        'Contract Value',
        'Description',
        'CLIN Number',
        'NSN',
        'NSN Description',
        'Supplier',
        'Quantity',
        'Unit Price',
        'Total Price',
        'CLIN Description'
    ])
    
    return response

def download_test_data(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="test_contracts.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Contract Number',
        'Buyer',
        'Award Date',
        'Due Date',
        'Contract Value',
        'Description',
        'CLIN Number',
        'NSN',
        'NSN Description',
        'Supplier',
        'Quantity',
        'Unit Price',
        'Total Price',
        'CLIN Description'
    ])
    
    # Add some test data
    writer.writerow([
        'TEST-2024-001',
        'Test Buyer 1',
        '2024-01-01',
        '2024-12-31',
        '100000.00',
        'Test Contract 1',
        '0001',
        '1234-56-789-0123',
        'Test NSN Description 1',
        'Test Supplier 1',
        '10',
        '1000.00',
        '10000.00',
        'Test CLIN Description 1'
    ])
    
    return response

def upload_csv(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        if not csv_file.name.endswith('.csv'):
            return JsonResponse({'success': False, 'error': 'Please upload a CSV file'})
        
        try:
            decoded_file = csv_file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file)
            
            for row in reader:
                # Create ContractQueue entry
                contract = ContractQueue.objects.create(
                    contract_number=row['Contract Number'],
                    buyer=row['Buyer'],
                    award_date=row['Award Date'],
                    due_date=row['Due Date'],
                    contract_value=row['Contract Value'],
                    description=row['Description']
                )
                
                # Create CLIN entries
                clin = contract.clins.create(
                    clin_number=row['CLIN Number'],
                    nsn=row['NSN'],
                    nsn_description=row['NSN Description'],
                    supplier=row['Supplier'],
                    quantity=row['Quantity'],
                    unit_price=row['Unit Price'],
                    total_price=row['Total Price'],
                    description=row['CLIN Description']
                )
            
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'}) 