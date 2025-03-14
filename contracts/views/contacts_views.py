from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView
from django.contrib import messages
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.db.models import Q, Count, Prefetch
from django.http import JsonResponse
from django.core.paginator import Paginator

from STATZWeb.decorators import conditional_login_required
from ..models import Contact, Address, Supplier
from ..forms import ContactForm, AddressForm

# Contact Views
@method_decorator(conditional_login_required, name='dispatch')
class ContactListView(ListView):
    model = Contact
    template_name = 'contracts/contacts/contact_list.html'
    context_object_name = 'contacts'
    paginate_by = 15
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('address')
        
        # Search functionality
        search_query = self.request.GET.get('q', '')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) | 
                Q(company__icontains=search_query) | 
                Q(email__icontains=search_query) |
                Q(phone__icontains=search_query)
            )
        
        # Sort functionality
        sort_by = self.request.GET.get('sort', 'name')
        if sort_by.startswith('-'):
            sort_field = sort_by[1:]
            direction = '-'
        else:
            sort_field = sort_by
            direction = ''
        
        # Ensure the sort field exists in the model
        valid_fields = ['name', 'company', 'email', 'created_on']
        if sort_field in valid_fields:
            queryset = queryset.order_by(f'{direction}{sort_field}')
        else:
            queryset = queryset.order_by('name')
            
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        context['sort_by'] = self.request.GET.get('sort', 'name')
        # Count related suppliers for each contact
        supplier_counts = Supplier.objects.filter(contact__in=context['contacts']).values('contact').annotate(count=Count('id'))
        supplier_counts_dict = {item['contact']: item['count'] for item in supplier_counts}
        
        # Add supplier count to each contact
        for contact in context['contacts']:
            contact.supplier_count = supplier_counts_dict.get(contact.id, 0)
            
        return context

@method_decorator(conditional_login_required, name='dispatch')
class ContactDetailView(DetailView):
    model = Contact
    template_name = 'contracts/contacts/contact_detail.html'
    context_object_name = 'contact'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['related_suppliers'] = Supplier.objects.filter(contact=self.object).select_related('supplier_type')
        return context

@method_decorator(conditional_login_required, name='dispatch')
class ContactCreateView(CreateView):
    model = Contact
    form_class = ContactForm
    template_name = 'contracts/contacts/contact_form.html'
    
    def get_success_url(self):
        messages.success(self.request, 'Contact created successfully.')
        if 'supplier_id' in self.request.GET:
            return reverse('contracts:supplier_detail', kwargs={'pk': self.request.GET.get('supplier_id')})
        return reverse('contracts:contact_detail', kwargs={'pk': self.object.pk})
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['addresses'] = Address.objects.all().order_by('-id')[:10]  # Show last 10 addresses for quick selection
        context['supplier_id'] = self.request.GET.get('supplier_id')
        context['title'] = 'Create New Contact'
        context['submit_text'] = 'Create Contact'
        
        # If we're doing an AJAX refresh and have an address ID in POST data
        if self.request.method == 'POST' and self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            address_id = self.request.POST.get('address')
            if address_id:
                try:
                    context['address'] = Address.objects.get(pk=address_id)
                except Address.DoesNotExist:
                    pass
        
        return context
    
    def form_valid(self, form):
        response = super().form_valid(form)
        
        # If contact created from supplier, update the supplier with this contact
        supplier_id = self.request.GET.get('supplier_id')
        if supplier_id:
            try:
                supplier = Supplier.objects.get(id=supplier_id)
                supplier.contact = self.object
                supplier.save()
                messages.info(self.request, f'Contact assigned to supplier {supplier.name}.')
            except Supplier.DoesNotExist:
                pass
                
        return response

@method_decorator(conditional_login_required, name='dispatch')
class ContactUpdateView(UpdateView):
    model = Contact
    form_class = ContactForm
    template_name = 'contracts/contacts/contact_form.html'
    
    def get_success_url(self):
        messages.success(self.request, 'Contact updated successfully.')
        return reverse('contracts:contact_detail', kwargs={'pk': self.object.pk})
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['addresses'] = Address.objects.all().order_by('-id')[:10]  # Show last 10 addresses
        context['title'] = 'Update Contact'
        context['submit_text'] = 'Update Contact'
        
        # Add the address object to the context if an address is assigned
        if self.object.address:
            context['address'] = self.object.address
        
        return context

@method_decorator(conditional_login_required, name='dispatch')
class ContactDeleteView(DeleteView):
    model = Contact
    template_name = 'contracts/contacts/contact_confirm_delete.html'
    success_url = reverse_lazy('contracts:contact_list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Check if contact is used by any suppliers
        context['suppliers_using_contact'] = Supplier.objects.filter(contact=self.object)
        return context
    
    def post(self, request, *args, **kwargs):
        suppliers_using_contact = Supplier.objects.filter(contact=self.get_object())
        if suppliers_using_contact.exists():
            messages.error(request, "Cannot delete this contact because it is used by one or more suppliers. Please remove the contact from those suppliers first.")
            return redirect('contracts:contact_detail', pk=self.get_object().pk)
        
        messages.success(request, 'Contact deleted successfully.')
        return super().post(request, *args, **kwargs)

# Address Views
@method_decorator(conditional_login_required, name='dispatch')
class AddressListView(ListView):
    model = Address
    template_name = 'contracts/contacts/address_list.html'
    context_object_name = 'addresses'
    paginate_by = 15
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Search functionality
        search_query = self.request.GET.get('q', '')
        if search_query:
            queryset = queryset.filter(
                Q(address_line_1__icontains=search_query) | 
                Q(city__icontains=search_query) | 
                Q(state__icontains=search_query) |
                Q(zip__icontains=search_query)
            )
        
        # Sort by
        sort_by = self.request.GET.get('sort', '-id')
        valid_fields = ['address_line_1', 'city', 'state', 'zip', 'id']
        
        if sort_by.startswith('-'):
            sort_field = sort_by[1:]
        else:
            sort_field = sort_by
            
        if sort_field in valid_fields:
            queryset = queryset.order_by(sort_by)
        else:
            queryset = queryset.order_by('-id')
            
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        context['sort_by'] = self.request.GET.get('sort', '-id')
        
        # Count relationships for each address
        for address in context['addresses']:
            address.supplier_billing_count = Supplier.objects.filter(billing_address=address).count()
            address.supplier_shipping_count = Supplier.objects.filter(shipping_address=address).count()
            address.supplier_physical_count = Supplier.objects.filter(physical_address=address).count()
            address.contact_count = Contact.objects.filter(address=address).count()
            address.total_usage = (
                address.supplier_billing_count + 
                address.supplier_shipping_count + 
                address.supplier_physical_count + 
                address.contact_count
            )
            
        return context

@method_decorator(conditional_login_required, name='dispatch')
class AddressDetailView(DetailView):
    model = Address
    template_name = 'contracts/contacts/address_detail.html'
    context_object_name = 'address'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Related entities
        context['suppliers_billing'] = Supplier.objects.filter(billing_address=self.object)
        context['suppliers_shipping'] = Supplier.objects.filter(shipping_address=self.object)
        context['suppliers_physical'] = Supplier.objects.filter(physical_address=self.object)
        context['contacts'] = Contact.objects.filter(address=self.object)
        
        return context

@method_decorator(conditional_login_required, name='dispatch')
class AddressCreateView(CreateView):
    model = Address
    form_class = AddressForm
    template_name = 'contracts/contacts/address_form.html'
    
    def get_success_url(self):
        if self.request.GET.get('popup') == 'true':
            # For popup mode, return success page with JavaScript to close window
            return reverse_lazy('contracts:address_create_success')
        return reverse_lazy('contracts:address_list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create New Address'
        context['submit_text'] = 'Create Address'
        context['is_popup'] = self.request.GET.get('popup') == 'true'
        return context
    
    def form_valid(self, form):
        response = super().form_valid(form)
        
        # If AJAX request (from contact form), return the new address data
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'address_id': self.object.id,
                'address_text': str(self.object)
            })
            
        return response

@method_decorator(conditional_login_required, name='dispatch')
class AddressUpdateView(UpdateView):
    model = Address
    form_class = AddressForm
    template_name = 'contracts/contacts/address_form.html'
    
    def get_success_url(self):
        messages.success(self.request, 'Address updated successfully.')
        return reverse('contracts:address_detail', kwargs={'pk': self.object.pk})
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Update Address'
        return context

@method_decorator(conditional_login_required, name='dispatch')
class AddressDeleteView(DeleteView):
    model = Address
    template_name = 'contracts/contacts/address_confirm_delete.html'
    success_url = reverse_lazy('contracts:address_list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Check all relationships
        context['suppliers_billing'] = Supplier.objects.filter(billing_address=self.object)
        context['suppliers_shipping'] = Supplier.objects.filter(shipping_address=self.object)
        context['suppliers_physical'] = Supplier.objects.filter(physical_address=self.object)
        context['contacts'] = Contact.objects.filter(address=self.object)
        
        # Determine if deletion is safe
        context['is_in_use'] = (
            context['suppliers_billing'].exists() or
            context['suppliers_shipping'].exists() or
            context['suppliers_physical'].exists() or
            context['contacts'].exists()
        )
        
        return context
    
    def post(self, request, *args, **kwargs):
        # Perform one final check before deletion
        address = self.get_object()
        
        suppliers_billing = Supplier.objects.filter(billing_address=address)
        suppliers_shipping = Supplier.objects.filter(shipping_address=address)
        suppliers_physical = Supplier.objects.filter(physical_address=address) 
        contacts = Contact.objects.filter(address=address)
        
        if suppliers_billing.exists() or suppliers_shipping.exists() or suppliers_physical.exists() or contacts.exists():
            messages.error(request, "Cannot delete this address because it is in use. Please remove all references to this address first.")
            return redirect('contracts:address_detail', pk=address.pk)
        
        messages.success(request, 'Address deleted successfully.')
        return super().post(request, *args, **kwargs)

@method_decorator(conditional_login_required, name='dispatch')
class AddressSelectorView(TemplateView):
    template_name = 'contracts/contacts/address_selector.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get filter parameters from request
        state_filter = self.request.GET.get('state', '')
        city_filter = self.request.GET.get('city', '')
        search_query = self.request.GET.get('q', '')
        current_id = self.request.GET.get('current_id', '')
        target_field = self.request.GET.get('target_field', 'id_address')
        target_form = self.request.GET.get('target_form', '')
        
        # Get page number for pagination
        page = self.request.GET.get('page', 1)
        try:
            page = int(page)
        except ValueError:
            page = 1
        
        # Apply filters to addresses
        addresses = Address.objects.all().order_by('state', 'city', 'address_line_1')
        
        # Get unique states and cities for the filter dropdowns
        states = Address.objects.values_list('state', flat=True).distinct().order_by('state')
        
        # Filter cities based on selected state
        if state_filter:
            cities = Address.objects.filter(state=state_filter).values_list('city', flat=True).distinct().order_by('city')
            addresses = addresses.filter(state=state_filter)
        else:
            cities = Address.objects.values_list('city', flat=True).distinct().order_by('city')
        
        # Apply city filter if provided
        if city_filter:
            addresses = addresses.filter(city=city_filter)
        
        # Apply search query if provided
        if search_query:
            addresses = addresses.filter(
                Q(address_line_1__icontains=search_query) |
                Q(address_line_2__icontains=search_query) |
                Q(city__icontains=search_query) |
                Q(state__icontains=search_query) |
                Q(zip__icontains=search_query) |
                Q(country__icontains=search_query)
            )
        
        # Create paginator - show 5 addresses per page instead of 10
        paginator = Paginator(addresses, 5)  # Show 5 addresses per page
        page_obj = paginator.get_page(page)
        
        # Add all required context
        context.update({
            'addresses': page_obj,
            'total_count': addresses.count(),
            'states': states,
            'cities': cities,
            'state_filter': state_filter,
            'city_filter': city_filter,
            'search_query': search_query,
            'current_id': current_id,
            'target_field': target_field,
            'target_form': target_form,
            'current_page': page,
            'total_pages': paginator.num_pages,
            'has_previous': page_obj.has_previous(),
            'has_next': page_obj.has_next(),
            'previous_page': page_obj.previous_page_number() if page_obj.has_previous() else None,
            'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
        })
        
        return context

@method_decorator(conditional_login_required, name='dispatch')
class AddressCreateSuccessView(TemplateView):
    template_name = 'contracts/contacts/address_create_success.html' 