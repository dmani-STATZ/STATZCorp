from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import redirect, render

from ..forms import (
    ContractTypeForm,
    ClinTypeForm,
    SalesClassForm,
    SpecialPaymentTermsForm,
)
from ..models import (
    Clin,
    ClinType,
    Contract,
    ContractType,
    SalesClass,
    SpecialPaymentTerms,
    Supplier,
)


TABLE_CONFIG = [
    {
        "key": "contract_types",
        "title": "Contract Types",
        "description": "Controls the values available for the contract type field when creating or editing a contract.",
        "model": ContractType,
        "form_class": ContractTypeForm,
        "order_by": "description",
        "columns": [
            {"header": "Description", "attr": "description"},
        ],
        "usage_checks": [
            {
                "label": "contracts",
                "check": lambda object_id: Contract.objects.filter(
                    contract_type_id=object_id
                ).exists(),
            },
        ],
    },
    {
        "key": "sales_classes",
        "title": "Sales Classes",
        "description": "Drive the sales class dropdown on contract records.",
        "model": SalesClass,
        "form_class": SalesClassForm,
        "order_by": "sales_team",
        "columns": [
            {"header": "Sales Team", "attr": "sales_team"},
        ],
        "usage_checks": [
            {
                "label": "contracts",
                "check": lambda object_id: Contract.objects.filter(
                    sales_class_id=object_id
                ).exists(),
            },
        ],
    },
    {
        "key": "special_payment_terms",
        "title": "Special Payment Terms",
        "description": "Shared by CLINs and suppliers for bespoke payment arrangements.",
        "model": SpecialPaymentTerms,
        "form_class": SpecialPaymentTermsForm,
        "order_by": "terms",
        "columns": [
            {"header": "Code", "attr": "code"},
            {"header": "Terms", "attr": "terms"},
        ],
        "usage_checks": [
            {
                "label": "CLINs",
                "check": lambda object_id: Clin.objects.filter(
                    special_payment_terms_id=object_id
                ).exists(),
            },
            {
                "label": "suppliers",
                "check": lambda object_id: Supplier.objects.filter(
                    special_terms_id=object_id
                ).exists(),
            },
        ],
    },
    {
        "key": "clin_types",
        "title": "CLIN Types",
        "description": "Used when assigning CLIN type data during processing.",
        "model": ClinType,
        "form_class": ClinTypeForm,
        "order_by": "description",
        "columns": [
            {"header": "Description", "attr": "description"},
            {"header": "Raw Text", "attr": "raw_text"},
        ],
        "usage_checks": [
            {
                "label": "CLINs",
                "check": lambda object_id: Clin.objects.filter(
                    clin_type_id=object_id
                ).exists(),
            },
        ],
    },
]

TABLE_LOOKUP = {config["key"]: config for config in TABLE_CONFIG}


@login_required
@user_passes_test(lambda user: user.is_superuser)
def code_table_admin(request):
    """
    Superuser-only view for managing common code tables used during contract entry.
    """
    table_forms = {}

    if request.method == "POST":
        table_key = request.POST.get("table")
        action = request.POST.get("action")
        config = TABLE_LOOKUP.get(table_key)

        if not config:
            messages.error(request, "Unknown code table request.")
            return redirect("contracts:code_table_admin")

        if action == "create":
            form = config["form_class"](request.POST)
            if form.is_valid():
                instance = form.save()
                messages.success(
                    request,
                    f"Added “{instance}” to {config['title'].lower()}.",
                )
                return redirect("contracts:code_table_admin")

            table_forms[table_key] = form
        elif action == "delete":
            object_id = request.POST.get("object_id")
            if not object_id:
                messages.error(request, "Missing selection to delete.")
                return redirect("contracts:code_table_admin")

            obj = config["model"].objects.filter(pk=object_id).first()
            if obj is None:
                messages.error(request, "Record not found.")
                return redirect("contracts:code_table_admin")

            in_use_labels = [
                check_config["label"]
                for check_config in config.get("usage_checks", [])
                if check_config["check"](obj.id)
            ]

            if in_use_labels:
                labels = ", ".join(in_use_labels)
                messages.error(
                    request,
                    f"Unable to delete “{obj}” because it is referenced by {labels}.",
                )
                return redirect("contracts:code_table_admin")

            obj.delete()
            messages.success(
                request,
                f"Removed “{obj}” from {config['title'].lower()}.",
            )
            return redirect("contracts:code_table_admin")

        else:
            messages.error(request, "Unsupported action.")
            return redirect("contracts:code_table_admin")

    tables_context = []
    for config in TABLE_CONFIG:
        form = table_forms.get(config["key"], config["form_class"]())
        items = config["model"].objects.all()
        order_by = config.get("order_by")
        if order_by:
            items = items.order_by(order_by)

        columns = config.get("columns", [])
        rows = []
        for entry in items:
            row = []
            for column in columns:
                attr_name = column.get("attr")
                value = getattr(entry, attr_name, None) if attr_name else None

                if value is None:
                    display_value = "—"
                elif isinstance(value, str):
                    display_value = value.strip() or "—"
                else:
                    display_value = value

                row.append(display_value)
            rows.append({"id": entry.id, "values": row})

        tables_context.append(
            {
                "key": config["key"],
                "title": config["title"],
                "description": config.get("description", ""),
                "form": form,
                "columns": columns,
                "rows": rows,
            }
        )

    context = {
        "tables": tables_context,
        "ia_choices": Clin.ORIGIN_DESTINATION_CHOICES,
        "fob_choices": Clin.ORIGIN_DESTINATION_CHOICES,
    }

    return render(request, "contracts/code_table_admin.html", context)
