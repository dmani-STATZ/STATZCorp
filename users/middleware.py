from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth import get_user_model
from contracts.models import Company
from users.models import UserCompanyMembership


class ActiveCompanyMiddleware(MiddlewareMixin):
    """
    Attaches request.active_company for authenticated users based on:
    1) Session-stored company id (if valid and allowed), else
    2) User's default membership (or first membership), else
    3) Global default company (Company.get_default_company)
    """

    def process_request(self, request):
        request.active_company = None

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return

        # Try session company first
        company_id = request.session.get("active_company_id")
        company = None

        if company_id:
            try:
                company = Company.objects.get(pk=company_id, is_active=True)
            except Company.DoesNotExist:
                company = None

            # Enforce membership unless superuser
            if company and not user.is_superuser:
                if not UserCompanyMembership.objects.filter(user=user, company=company).exists():
                    company = None

            if not company:
                # Clean invalid session value
                request.session.pop("active_company_id", None)

        # Fallbacks: default membership -> any membership -> default company
        if not company:
            default_membership = UserCompanyMembership.objects.filter(user=user, is_default=True).select_related("company").first()
            if default_membership:
                company = default_membership.company
                request.session["active_company_id"] = company.id
            else:
                any_membership = UserCompanyMembership.objects.filter(user=user).select_related("company").first()
                if any_membership:
                    company = any_membership.company
                    request.session["active_company_id"] = company.id
                else:
                    company = Company.get_default_company()
                    request.session["active_company_id"] = company.id

        request.active_company = company

