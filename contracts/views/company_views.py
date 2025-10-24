from django.urls import reverse_lazy
from django.contrib import messages
from django.shortcuts import redirect
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, CreateView, UpdateView, TemplateView
from django.db.models import Count

from contracts.models import Company
from contracts.forms import CompanyForm
from contracts.models import Contract, Clin
from processing.models import QueueContract, QueueClin, ProcessContract, ProcessClin
from users.models import UserCompanyMembership


class SuperuserRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser

    def handle_no_permission(self):
        messages.error(self.request, 'You do not have permission to access Company management.')
        return redirect('users:permission_denied')


class CompanyListView(LoginRequiredMixin, SuperuserRequiredMixin, ListView):
    model = Company
    template_name = 'contracts/company_list.html'
    context_object_name = 'companies'
    paginate_by = 25

    def get_queryset(self):
        return super().get_queryset().annotate(user_count=Count('user_memberships', distinct=True))


class CompanyCreateView(LoginRequiredMixin, SuperuserRequiredMixin, CreateView):
    model = Company
    form_class = CompanyForm
    template_name = 'contracts/company_form.html'
    success_url = reverse_lazy('contracts:company_list')

    def form_valid(self, form):
        messages.success(self.request, 'Company created successfully.')
        return super().form_valid(form)


class CompanyUpdateView(LoginRequiredMixin, SuperuserRequiredMixin, UpdateView):
    model = Company
    form_class = CompanyForm
    template_name = 'contracts/company_form.html'
    success_url = reverse_lazy('contracts:company_list')

    def form_valid(self, form):
        messages.success(self.request, 'Company updated successfully.')
        return super().form_valid(form)


class CompanyDeleteView(LoginRequiredMixin, SuperuserRequiredMixin, TemplateView):
    template_name = 'contracts/company_confirm_delete.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = Company.objects.get(pk=self.kwargs['pk'])
        context['company'] = company
        # Related counts for safety checks
        context['related_counts'] = {
            'contracts': Contract.objects.filter(company=company).count(),
            'clins': Clin.objects.filter(company=company).count(),
            'queue_contracts': QueueContract.objects.filter(company=company).count(),
            'queue_clins': QueueClin.objects.filter(company=company).count(),
            'process_contracts': ProcessContract.objects.filter(company=company).count(),
            'process_clins': ProcessClin.objects.filter(company=company).count(),
            'memberships': UserCompanyMembership.objects.filter(company=company).count(),
        }
        return context

    def post(self, request, *args, **kwargs):
        company = Company.objects.get(pk=kwargs['pk'])
        blockers = []
        if Contract.objects.filter(company=company).exists():
            blockers.append('contracts')
        if Clin.objects.filter(company=company).exists():
            blockers.append('CLINs')
        if QueueContract.objects.filter(company=company).exists():
            blockers.append('queue contracts')
        if QueueClin.objects.filter(company=company).exists():
            blockers.append('queue CLINs')
        if ProcessContract.objects.filter(company=company).exists():
            blockers.append('processing contracts')
        if ProcessClin.objects.filter(company=company).exists():
            blockers.append('processing CLINs')
        if UserCompanyMembership.objects.filter(company=company).exists():
            blockers.append('user memberships')

        if blockers:
            messages.error(request, f"Cannot delete company. Remove related data first: {', '.join(blockers)}.")
            return redirect('contracts:company_list')

        name = company.name
        company.delete()
        messages.success(request, f'Company "{name}" deleted successfully.')
        return redirect('contracts:company_list')
