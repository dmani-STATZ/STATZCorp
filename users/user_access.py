"""
User Access service layer (superuser-only admin page at /users/access/).

How access actually works in this project (keep this in sync if any of it changes):

* Sign-in: ModelBackend and MicrosoftAuthBackend both refuse users with
  ``is_active=False`` and both drop them when restoring a session, so
  ``is_active`` is the single "disabled" switch.
* App entry: ``STATZWeb.middleware.LoginRequiredMiddleware`` (only when
  ``REQUIRE_LOGIN``) resolves the URL namespace, looks it up in ``AppRegistry``
  (ignoring ``is_active``) and requires an ``AppPermission`` row with
  ``has_access=True``. No registry row = open to every signed-in user.
  Superusers bypass the check. The ``users`` and ``admin`` namespaces are exempt.
* Training: entry is the ``training`` app grant (only enforced if ``training`` is
  registered). What a user must complete comes from ``training.UserAccount``
  links -> active ``Matrix`` rows. Arctic Wolf tracking covers active
  ``is_staff`` users, limited to courses created on/after the user's join date.

Disable keeps grants, training links and completion history; it only flips
``is_active`` and drops the stored Microsoft token. Reactivate flips it back.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.contrib.auth.models import BaseUserManager
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, transaction

from .models import AppPermission, AppRegistry, UserOAuthToken

User = get_user_model()

TRAINING_APP_NAME = "training"


class UserAccessError(Exception):
    """Raised when an access change is refused (self-disable, last superuser, ...)."""


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def registry_apps():
    """Every registry row, active first. Middleware enforces inactive rows too."""
    return list(AppRegistry.objects.order_by("-is_active", "display_name"))


def granted_app_ids(user) -> set[int]:
    return set(
        AppPermission.objects.filter(user=user, has_access=True).values_list(
            "app_name_id", flat=True
        )
    )


def training_registered() -> bool:
    return AppRegistry.objects.filter(app_name=TRAINING_APP_NAME).exists()


def training_account_choices():
    from training.models import Account

    return list(Account.objects.order_by("type"))


def training_account_ids(user) -> set[int]:
    from training.models import UserAccount

    return set(
        UserAccount.objects.filter(user=user).values_list("account_id", flat=True)
    )


def arctic_wolf_summary(user) -> dict:
    """Derived, read-only: Arctic Wolf tracking is driven by is_staff + join date."""
    from training.models import ArcticWolfCourse
    from training.views import eligible_aw_course_ids_for_user

    courses = list(ArcticWolfCourse.objects.only("id", "created_at"))
    eligible = eligible_aw_course_ids_for_user(user, courses) if user.pk else set()
    return {
        "tracked": bool(user.is_active and user.is_staff),
        "eligible_count": len(eligible),
        "total_count": len(courses),
    }


def active_superuser_count() -> int:
    return User.objects.filter(is_superuser=True, is_active=True).count()


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def normalize_email(email: str) -> str:
    return BaseUserManager.normalize_email((email or "").strip())


def email_in_use(email: str, exclude_user_id=None) -> bool:
    qs = User.objects.filter(email__iexact=email)
    if exclude_user_id:
        qs = qs.exclude(pk=exclude_user_id)
    return qs.exists()


def username_from_email(email: str) -> str:
    """Same rule as MicrosoftAuthBackend auto-create: local part, numeric suffix if taken."""
    base = (email.split("@")[0] or "user")[:140]
    username = base
    counter = 1
    while User.objects.filter(username__iexact=username).exists():
        username = f"{base}{counter}"
        counter += 1
    return username


def set_app_access(user, app_ids) -> None:
    """Replace the user's grants for every registry app shown in the editor.

    Checked -> one ``has_access=True`` row. Unchecked -> row removed (denied).
    """
    wanted = {int(i) for i in app_ids}
    all_ids = set(AppRegistry.objects.values_list("id", flat=True))
    wanted &= all_ids
    AppPermission.objects.filter(user=user, app_name_id__in=all_ids - wanted).delete()
    for app_id in wanted:
        AppPermission.objects.update_or_create(
            user=user, app_name_id=app_id, defaults={"has_access": True}
        )


def set_training_accounts(user, account_ids) -> None:
    """Sync CMMC account-type links. Tracker history is keyed by user+matrix and is untouched."""
    from training.models import Account, UserAccount

    wanted = {int(i) for i in account_ids}
    wanted.intersection_update(Account.objects.values_list("pk", flat=True))
    current = training_account_ids(user)
    UserAccount.objects.filter(user=user, account_id__in=current - wanted).delete()
    for account_id in wanted - current:
        UserAccount.objects.create(user=user, account_id=account_id)


def save_account(user, *, update_fields=None):
    try:
        user.full_clean(exclude={"password"}, validate_unique=False)
    except ValidationError as exc:
        raise UserAccessError(" ".join(exc.messages)) from exc
    try:
        user.save(update_fields=update_fields)
    except (DataError, IntegrityError) as exc:
        raise UserAccessError("Account could not be saved. Check the field values and whether the username is already taken.") from exc


@transaction.atomic
def create_user(
    *,
    email,
    first_name="",
    last_name="",
    username="",
    app_ids=(),
    training_account_ids_=(),
):
    """Provision a standard (non-superuser) account for Microsoft sign-in.

    The local password is unusable; the user signs in with Microsoft, which
    matches the account by email.
    """
    email = normalize_email(email)
    if not email:
        raise UserAccessError("Email is required.")
    if email_in_use(email):
        raise UserAccessError(f"A user with email {email} already exists.")
    username = (username or "").strip() or username_from_email(email)
    if User.objects.filter(username__iexact=username).exists():
        raise UserAccessError(f"Username {username} is already taken.")

    user = User(
        username=username,
        email=email,
        first_name=(first_name or "").strip(),
        last_name=(last_name or "").strip(),
        is_staff=False,
        is_superuser=False,
        is_active=True,
    )
    user.set_unusable_password()
    save_account(user)
    set_app_access(user, app_ids)
    set_training_accounts(user, training_account_ids_)
    return user


@transaction.atomic
def update_user(
    user,
    *,
    email,
    first_name="",
    last_name="",
    is_staff=False,
    app_ids=(),
    training_account_ids_=(),
):
    email = normalize_email(email)
    if not email:
        raise UserAccessError("Email is required.")
    if email_in_use(email, exclude_user_id=user.pk):
        raise UserAccessError(f"Another user already has email {email}.")
    user.email = email
    user.first_name = (first_name or "").strip()
    user.last_name = (last_name or "").strip()
    user.is_staff = bool(is_staff)
    save_account(user, update_fields=["email", "first_name", "last_name", "is_staff"])
    set_app_access(user, app_ids)
    set_training_accounts(user, training_account_ids_)
    return user


@transaction.atomic
def disable_user(actor, user) -> None:
    if user.pk == actor.pk:
        raise UserAccessError("You can't disable your own account.")
    if not user.is_active:
        return
    # Lock superuser rows so two concurrent disables can't both pass the check.
    if user.is_superuser:
        active_supers = list(
            User.objects.select_for_update()
            .filter(is_superuser=True, is_active=True)
            .values_list("pk", flat=True)
        )
        if len(active_supers) <= 1:
            raise UserAccessError("You can't disable the last active superuser.")
    user.is_active = False
    user.save(update_fields=["is_active"])
    # Stored Graph tokens let server code act as this user; drop them.
    # They are re-issued at the next Microsoft sign-in after reactivation.
    UserOAuthToken.objects.filter(user=user).delete()


@transaction.atomic
def reactivate_user(user) -> list[str]:
    """Re-enable the account. Returns display names of the app grants that come back."""
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])
    return list(
        AppPermission.objects.filter(user=user, has_access=True)
        .select_related("app_name")
        .order_by("app_name__display_name")
        .values_list("app_name__display_name", flat=True)
    )


@dataclass
class AccessFormData:
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    is_staff: bool = False
    app_ids: set = field(default_factory=set)
    training_account_ids: set = field(default_factory=set)

    @classmethod
    def from_post(cls, post):
        def ids(name):
            return {int(v) for v in post.getlist(name) if len(v) <= 19 and v.isascii() and v.isdecimal()}

        return cls(
            email=post.get("email", "").strip(),
            first_name=post.get("first_name", "").strip(),
            last_name=post.get("last_name", "").strip(),
            username=post.get("username", "").strip(),
            is_staff=post.get("is_staff") == "on",
            app_ids=ids("apps"),
            training_account_ids=ids("training_accounts"),
        )

    @classmethod
    def from_user(cls, user):
        return cls(
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            is_staff=user.is_staff,
            app_ids=granted_app_ids(user),
            training_account_ids=training_account_ids(user),
        )
