from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView, View

from ..forms import PodVsCustomerPayFilterForm
from ..services.pod_vs_customer_pay import (
    PAGE_SIZE,
    SECTION_NOT_PAID,
    SECTION_UNDERPAID,
    SECTIONS,
    VIEW_SHIPMENT,
    build_pod_pay_csv,
    compute_pod_pay_report,
)
from .mixins import ActiveCompanyQuerysetMixin

# GET parameter holding each section's page number. Each section pages on its own.
PAGE_PARAMS = {SECTION_NOT_PAID: "np_page", SECTION_UNDERPAID: "up_page"}


def _page_query(get_params, param: str, number: int) -> str:
    params = get_params.copy()
    params[param] = str(number)
    return params.urlencode()


@method_decorator(login_required, name="dispatch")
class PodVsCustomerPayReportView(ActiveCompanyQuerysetMixin, TemplateView):
    template_name = "contracts/pod_vs_customer_pay_report.html"
    http_method_names = ["get"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.get_active_company()
        form = PodVsCustomerPayFilterForm(self.request.GET)
        report = None
        sections = []
        if form.is_valid():
            filters = form.to_filters()
            report = compute_pod_pay_report(company, filters, as_of=timezone.localdate())
            for key, label in SECTIONS:
                rows = report["sections"][key]
                param = PAGE_PARAMS[key]
                page = Paginator(rows, PAGE_SIZE).get_page(self.request.GET.get(param))
                sections.append(
                    {
                        "key": key,
                        "label": label,
                        "total": len(rows),
                        "page": page,
                        "prev_query": (
                            _page_query(self.request.GET, param, page.previous_page_number())
                            if page.has_previous() else ""
                        ),
                        "next_query": (
                            _page_query(self.request.GET, param, page.next_page_number())
                            if page.has_next() else ""
                        ),
                    }
                )
        export_params = self.request.GET.copy()
        for param in PAGE_PARAMS.values():
            export_params.pop(param, None)
        context.update(
            form=form,
            report=report,
            sections=sections,
            shipment_view=bool(report and report["view"] == VIEW_SHIPMENT),
            export_query=export_params.urlencode(),
        )
        return context


@method_decorator(login_required, name="dispatch")
class PodVsCustomerPayExportView(ActiveCompanyQuerysetMixin, View):
    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        company = self.get_active_company()
        form = PodVsCustomerPayFilterForm(request.GET)
        if not form.is_valid():
            return HttpResponseBadRequest(form.errors.as_text(), content_type="text/plain")
        as_of = timezone.localdate()
        report = compute_pod_pay_report(company, form.to_filters(), as_of=as_of)
        response = HttpResponse(build_pod_pay_csv(report), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="pod_vs_customer_pay_{report["view"]}_{as_of:%Y-%m-%d}.csv"'
        )
        return response


pod_vs_customer_pay_report = PodVsCustomerPayReportView.as_view()
pod_vs_customer_pay_export = PodVsCustomerPayExportView.as_view()
