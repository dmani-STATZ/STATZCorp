from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth import get_user_model
from contracts.models import Company
from users.models import UserCompanyMembership
from users.user_settings import UserSettings


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

        # If no valid company from session, try persisted user setting
        if not company:
            try:
                setting_val = UserSettings.get_setting(user, "current_company_id", default=None)
                # Normalize to int if possible
                if isinstance(setting_val, str) and setting_val.isdigit():
                    setting_company_id = int(setting_val)
                else:
                    setting_company_id = setting_val

                if setting_company_id:
                    try:
                        candidate = Company.objects.get(pk=setting_company_id, is_active=True)
                        # Enforce membership unless superuser
                        if user.is_superuser or UserCompanyMembership.objects.filter(user=user, company=candidate).exists():
                            company = candidate
                            request.session["active_company_id"] = candidate.id
                    except Company.DoesNotExist:
                        pass
            except Exception:
                # Ignore settings errors; fall back as usual
                pass

        # Fallbacks: default membership -> any membership -> default company
        if not company:
            default_membership = UserCompanyMembership.objects.filter(user=user, is_default=True).select_related("company").first()
            if default_membership:
                company = default_membership.company
                request.session["active_company_id"] = company.id
                # Persist selection for future sessions
                UserSettings.save_setting(user, "current_company_id", company.id, setting_type="integer", description="User's currently selected company")
            else:
                any_membership = UserCompanyMembership.objects.filter(user=user).select_related("company").first()
                if any_membership:
                    company = any_membership.company
                    request.session["active_company_id"] = company.id
                    UserSettings.save_setting(user, "current_company_id", company.id, setting_type="integer", description="User's currently selected company")
                else:
                    company = Company.get_default_company()
                    request.session["active_company_id"] = company.id
                    UserSettings.save_setting(user, "current_company_id", company.id, setting_type="integer", description="User's currently selected company")

        request.active_company = company
