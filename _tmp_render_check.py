from contracts.models import Contract, ContractPackaging
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from contracts.views.finance_views import FinanceAuditView
from django.template.loader import render_to_string

pkg = ContractPackaging.objects.select_related("contract").first()
if pkg is None:
    print("No ContractPackaging rows in DB.")
    raise SystemExit(0)

c = pkg.contract
User = get_user_model()
u = User.objects.filter(is_superuser=True).first() or User.objects.first()
rf = RequestFactory()
req = rf.get(f"/contracts/finance-audit/{c.pk}/")
req.user = u
req.active_company = c.company

view = FinanceAuditView()
view.request = req
view.kwargs = {"pk": c.pk}
view.object = c
ctx = view.get_context_data(object=c)
print("packaging in context:", ctx.get("packaging") is not None)
print("packaging_deduction:", ctx.get("packaging_deduction"))
print("adj_gross_contract:", ctx.get("adj_gross_contract"))

html = render_to_string("contracts/finance_audit.html", ctx, request=req)
print(f"Rendered finance_audit.html OK (len={len(html)})")
print("Has #packaging-finance-card:", 'id="packaging-finance-card"' in html)
print("Has #packagingFinanceModal:", 'id="packagingFinanceModal"' in html)
print("Has Details ->:", "Details \u2192" in html)
print("Has #packagingFinanceDetailsBtn:", 'id="packagingFinanceDetailsBtn"' in html)
