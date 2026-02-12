from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.contenttypes.models import ContentType

from .models import Transaction
from .forms import TransactionForm, EditFieldForm
from .field_types import get_field_info
from .utils import get_field_value_display, set_field_value, get_display_value


@login_required
@require_GET
def transaction_list(request, content_type_id, object_id):
    """List all transactions for a given object (e.g. a contract). For modal or inline."""
    ct = get_object_or_404(ContentType, pk=content_type_id)
    transactions = (
        Transaction.objects.filter(content_type=ct, object_id=object_id)
        .select_related("user")
        .order_by("-created_at")
    )
    return render(
        request,
        "transactions/partials/transaction_list.html",
        {"transactions": transactions, "content_type": ct, "object_id": object_id},
    )


@login_required
@require_GET
def transaction_detail(request, pk):
    """Detail of one transaction for the modal body (form with typed old/new value)."""
    transaction = get_object_or_404(Transaction.objects.select_related("user"), pk=pk)
    form = TransactionForm(
        content_type_id=transaction.content_type_id,
        field_name=transaction.field_name,
        instance=transaction,
    )
    return render(
        request,
        "transactions/partials/transaction_detail.html",
        {"transaction": transaction, "form": form},
    )


@login_required
@require_GET
def field_info_api(request):
    """Return widget type and choices for a model field. Used by modal form to pick input type."""
    content_type_id = request.GET.get("content_type_id")
    field_name = request.GET.get("field_name")
    if not content_type_id or not field_name:
        return JsonResponse({"error": "content_type_id and field_name required"}, status=400)
    info = get_field_info(int(content_type_id), field_name)
    if not info:
        return JsonResponse({"error": "Unknown model or field"}, status=404)
    return JsonResponse(info)


@login_required
def transaction_edit_field(request, content_type_id, object_id, field_name):
    """
    GET: Return HTML partial with edit form (table, field, old value, new value input) + history.
    POST: Validate, update model field, create Transaction, return JSON for page update.
    """
    ct = get_object_or_404(ContentType, pk=content_type_id)
    model_class = ct.model_class()
    if not model_class:
        return JsonResponse({"success": False, "error": "Unknown model"}, status=404)
    try:
        instance = model_class.objects.get(pk=object_id)
    except model_class.DoesNotExist:
        return JsonResponse({"success": False, "error": "Record not found"}, status=404)

    try:
        field = model_class._meta.get_field(field_name)
    except LookupError:
        return JsonResponse({"success": False, "error": "Unknown field"}, status=404)

    field_info = get_field_info(content_type_id, field_name)
    if not field_info:
        return JsonResponse({"success": False, "error": "Field not supported"}, status=400)

    if request.method == "POST":
        form = EditFieldForm(
            content_type_id=content_type_id,
            field_name=field_name,
            data=request.POST,
        )
        if not form.is_valid():
            return JsonResponse(
                {"success": False, "error": form.errors.get("new_value", ["Invalid value"])},
                status=400,
            )
        raw_new = form.cleaned_data.get("new_value") or ""
        if not set_field_value(instance, field_name, raw_new):
            return JsonResponse({"success": False, "error": "Could not set value"}, status=400)
        instance.save(update_fields=[field_name])
        new_display = get_display_value(instance, field_name)
        return JsonResponse({
            "success": True,
            "field_name": field_name,
            "content_type_id": content_type_id,
            "object_id": object_id,
            "display_value": new_display,
        })

    old_value_str = get_field_value_display(instance, field_name)
    form = EditFieldForm(
        content_type_id=content_type_id,
        field_name=field_name,
        initial_value=old_value_str,
    )
    transactions = (
        Transaction.objects.filter(content_type=ct, object_id=object_id, field_name=field_name)
        .select_related("user")
        .order_by("-created_at")[:20]
    )
    return render(
        request,
        "transactions/partials/transaction_edit.html",
        {
            "form": form,
            "table_name": ct.model,
            "field_name": field_name,
            "field_label": field_info.get("label", field_name),
            "old_value_display": get_display_value(instance, field_name),
            "transactions": transactions,
            "content_type_id": content_type_id,
            "object_id": object_id,
        },
    )
