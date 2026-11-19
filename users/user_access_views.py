"""Superuser-only User Access page: create users, grant apps/training, disable/reactivate.

Business logic lives in ``users/user_access.py``; these views only orchestrate.
The ``users`` namespace is exempt from AppPermission checks, so every view here
enforces superuser itself via ``superuser_required``.
"""
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from . import user_access as svc
from .models import AppPermission

User = get_user_model()


def superuser_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not (request.user.is_active and request.user.is_superuser):
            return render(request, "users/permission_denied.html", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def _editor_context(data, *, user=None):
    apps = svc.registry_apps()
    return {
        "data": data,
        "target": user,
        "registry_apps": apps,
        "app_permissions_enforced": settings.REQUIRE_LOGIN,
        "training_registered": svc.training_registered(),
        "training_accounts": svc.training_account_choices(),
        "arctic_wolf": svc.arctic_wolf_summary(user) if user else None,
    }


@superuser_required
@require_http_methods(["GET"])
def user_access_list(request):
    q = (request.GET.get("q") or "").strip()
    status = request.GET.get("status") or "active"

    users = User.objects.all().order_by("-is_active", "username")
    if status == "active":
        users = users.filter(is_active=True)
    elif status == "disabled":
        users = users.filter(is_active=False)
    if q:
        users = users.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )
    users = users.prefetch_related(
        Prefetch(
            "apppermission_set",
            queryset=AppPermission.objects.filter(has_access=True)
            .select_related("app_name")
            .order_by("app_name__display_name"),
            to_attr="granted_apps",
        ),
        "account_links__account",
    )

    page = Paginator(users, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "users/user_access_list.html",
        {
            "page_obj": page,
            "q": q,
            "status": status,
            "training_registered": svc.training_registered(),
        },
    )


@superuser_required
@require_http_methods(["GET", "POST"])
def user_access_create(request):
    if request.method == "POST":
        data = svc.AccessFormData.from_post(request.POST)
        try:
            user = svc.create_user(
                email=data.email,
                first_name=data.first_name,
                last_name=data.last_name,
                username=data.username,
                app_ids=data.app_ids,
                training_account_ids_=data.training_account_ids,
            )
        except svc.UserAccessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"Created {user.username}. They sign in with Microsoft as {user.email}.",
            )
            return redirect("users:user_access_edit", user_id=user.pk)
    else:
        data = svc.AccessFormData()
    return render(request, "users/user_access_form.html", _editor_context(data))


@superuser_required
@require_http_methods(["GET", "POST"])
def user_access_edit(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if request.method == "POST":
        data = svc.AccessFormData.from_post(request.POST)
        data.username = user.username
        try:
            svc.update_user(
                user,
                email=data.email,
                first_name=data.first_name,
                last_name=data.last_name,
                is_staff=data.is_staff,
                app_ids=data.app_ids,
                training_account_ids_=data.training_account_ids,
            )
        except svc.UserAccessError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Saved access for {user.username}.")
            return redirect("users:user_access_edit", user_id=user.pk)
    else:
        data = svc.AccessFormData.from_user(user)
    return render(request, "users/user_access_form.html", _editor_context(data, user=user))


@superuser_required
@require_POST
def user_access_disable(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    try:
        svc.disable_user(request.user, user)
    except svc.UserAccessError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Disabled {user.username}. They're signed out on their next request; "
            "their grants and training history are kept.",
        )
    return redirect("users:user_access_edit", user_id=user.pk)


@superuser_required
@require_POST
def user_access_reactivate(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    restored = svc.reactivate_user(user)
    if restored:
        messages.success(
            request, f"Reactivated {user.username}. Restored apps: {', '.join(restored)}."
        )
    else:
        messages.success(request, f"Reactivated {user.username}. They have no app grants.")
    return redirect("users:user_access_edit", user_id=user.pk)
