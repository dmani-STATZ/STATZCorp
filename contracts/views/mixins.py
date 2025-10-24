from django.core.exceptions import PermissionDenied


class ActiveCompanyQuerysetMixin:
    """
    Filters queryset by request.active_company for models that have a
    'company' ForeignKey. Ensures object access is company-scoped.
    """

    def get_active_company(self):
        company = getattr(self.request, 'active_company', None)
        if not company:
            raise PermissionDenied("No active company set")
        return company

    def get_queryset(self):
        qs = super().get_queryset()
        model = getattr(self, 'model', None)
        if model and any(f.name == 'company' for f in model._meta.fields):
            company = self.get_active_company()
            qs = qs.filter(company=company)
        return qs

