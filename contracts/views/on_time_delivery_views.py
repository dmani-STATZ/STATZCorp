from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView, View

from ..forms import OnTimeDeliveryFilterForm
from ..services.on_time_delivery import (
    build_otd_workbook,
    compute_otd_report,
    format_percent,
    unclassified_note,
)
from .mixins import ActiveCompanyQuerysetMixin

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@method_decorator(login_required, name="dispatch")
class OnTimeDeliveryReportView(ActiveCompanyQuerysetMixin, TemplateView):
    template_name = "contracts/on_time_delivery_report.html"
    http_method_names = ["get"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.get_active_company()
        report = None
        if "start_date" in self.request.GET:
            form = OnTimeDeliveryFilterForm(self.request.GET, company=company)
            if form.is_valid():
                report = compute_otd_report(company, form.to_filters())
                report["percent_labels"] = {
                    key: format_percent(value) for key, value in report["percents"].items()
                }
                report["unclassified_note"] = unclassified_note(report["unclassified"])
        else:
            form = OnTimeDeliveryFilterForm(company=company)
        context.update(
            form=form,
            report=report,
            query_string=self.request.GET.urlencode(),
        )
        return context


@method_decorator(login_required, name="dispatch")
class OnTimeDeliveryExportView(ActiveCompanyQuerysetMixin, View):
    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        company = self.get_active_company()
        form = OnTimeDeliveryFilterForm(request.GET, company=company)
        if not form.is_valid():
            return HttpResponseBadRequest(form.errors.as_text(), content_type="text/plain")

        filters = form.to_filters()
        report = compute_otd_report(company, filters)
        content = build_otd_workbook(
            report,
            company_name=company.name,
            filters=filters,
            buyer_labels=[b.description or "" for b in form.cleaned_data["buyer"]],
        )
        response = HttpResponse(content, content_type=XLSX_CONTENT_TYPE)
        response["Content-Disposition"] = (
            f'attachment; filename="on_time_delivery_{filters.start_date:%Y-%m-%d}_{filters.end_date:%Y-%m-%d}.xlsx"'
        )
        return response


on_time_delivery_report = OnTimeDeliveryReportView.as_view()
on_time_delivery_export = OnTimeDeliveryExportView.as_view()
