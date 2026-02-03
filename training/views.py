import json
from collections import defaultdict
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.db.models import Count, Q
from django.utils.text import get_valid_filename
from django.template.loader import render_to_string
from django.conf import settings
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors

from .forms import MatrixManagementForm, ArcticWolfCourseForm, CmmcDocumentUploadForm
from .models import (
    Matrix,
    Account,
    Course,
    UserAccount,
    Tracker,
    ArcticWolfCourse,
    ArcticWolfCompletion,
    CourseReviewClick,
    get_frequency_expiration_date,
)


def get_completion_status(completed_date, frequency, today=None):
    if not completed_date:
        return False, None
    if today is None:
        today = timezone.now().date()
    expiration_date = get_frequency_expiration_date(completed_date, frequency)
    if not expiration_date:
        return True, None
    return expiration_date >= today, expiration_date


def latest_completion_by_matrix(completions):
    latest = {}
    for completion in completions:
        if completion.matrix_id not in latest:
            latest[completion.matrix_id] = completion
    return latest


def latest_completion_by_course(completions):
    latest = {}
    for completion in completions:
        course_id = completion.matrix.course_id
        if course_id not in latest:
            latest[course_id] = completion
    return latest


def frequency_months(frequency):
    if frequency == "bi-annually":
        return 6
    if frequency == "annually":
        return 12
    return None


def pick_strictest_frequency(existing, candidate):
    if not existing:
        return candidate
    existing_months = frequency_months(existing)
    candidate_months = frequency_months(candidate)
    if existing_months is None:
        return candidate
    if candidate_months is None:
        return existing
    return candidate if candidate_months < existing_months else existing


def is_aw_course_required_for_user(user, course_created_at):
    if not course_created_at:
        return True
    if not user.date_joined:
        return True
    return user.date_joined.date() <= course_created_at.date()


def eligible_aw_course_ids_for_user(user, courses):
    return {
        course.id
        for course in courses
        if is_aw_course_required_for_user(user, course.created_at)
    }


@login_required
def dashboard(request):
    user = request.user

    # User-specific CMMC data
    today = timezone.now().date()
    user_account_ids = UserAccount.objects.filter(user=user).values_list(
        "account_id", flat=True
    )
    user_required_matrix_entries = Matrix.objects.filter(
        account__in=user_account_ids,
        is_active=True,
    ).distinct()
    user_total_required_courses = user_required_matrix_entries.count()
    user_completions = (
        Tracker.objects.filter(user=user, matrix__in=user_required_matrix_entries)
        .select_related("matrix")
        .order_by("-completed_date", "-id")
    )
    latest_user_completions = latest_completion_by_matrix(user_completions)
    user_completed_trainings = 0
    for matrix_entry in user_required_matrix_entries:
        completion = latest_user_completions.get(matrix_entry.id)
        is_current, _ = get_completion_status(
            completion.completed_date if completion else None,
            matrix_entry.frequency,
            today,
        )
        if is_current:
            user_completed_trainings += 1

    # CMMC Data for Pie Chart (considering non-staff users with accounts)
    # CMMC Training Matrix: Shows users where is_active=True AND is_staff=False
    cmmc_users_with_accounts = (
        UserAccount.objects.filter(user__is_active=True)
        .values_list("user_id", flat=True)
        .distinct()
    )
    total_possible_cmmc_trainings = 0
    total_completed_cmmc_trainings = 0

    for user_id in cmmc_users_with_accounts:
        user_account_ids = UserAccount.objects.filter(user_id=user_id).values_list(
            "account_id", flat=True
        )
        required_matrix_entries = Matrix.objects.filter(
            account__in=user_account_ids,
            is_active=True,
        ).distinct()
        total_possible_cmmc_trainings += required_matrix_entries.count()

        completions = (
            Tracker.objects.filter(user_id=user_id, matrix__in=required_matrix_entries)
            .select_related("matrix")
            .order_by("-completed_date", "-id")
        )
        latest_completions = latest_completion_by_matrix(completions)
        for matrix_entry in required_matrix_entries:
            completion = latest_completions.get(matrix_entry.id)
            is_current, _ = get_completion_status(
                completion.completed_date if completion else None,
                matrix_entry.frequency,
                today,
            )
            if is_current:
                total_completed_cmmc_trainings += 1

    uncompleted_cmmc_trainings = (
        total_possible_cmmc_trainings - total_completed_cmmc_trainings
        if total_possible_cmmc_trainings > 0
        else 0
    )

    # Arctic Wolf Data for Pie Chart (staff users only, excluding pre-hire courses)
    staff_users = list(User.objects.filter(is_active=True, is_staff=True))
    aw_courses = list(ArcticWolfCourse.objects.all())
    eligible_course_ids_by_user = {
        user.id: eligible_aw_course_ids_for_user(user, aw_courses)
        for user in staff_users
    }
    total_possible_aw_completions = sum(
        len(course_ids) for course_ids in eligible_course_ids_by_user.values()
    )
    staff_completions = ArcticWolfCompletion.objects.filter(
        user__in=staff_users
    ).values("user_id", "course_id")
    total_actual_aw_completions = sum(
        1
        for row in staff_completions
        if row["course_id"] in eligible_course_ids_by_user.get(row["user_id"], set())
    )
    uncompleted_aw_completions = (
        total_possible_aw_completions - total_actual_aw_completions
        if total_possible_aw_completions > 0
        else 0
    )

    eligible_aw_course_ids_for_current_user = eligible_aw_course_ids_for_user(
        user, aw_courses
    )
    aw_total_courses_count = len(eligible_aw_course_ids_for_current_user)
    aw_completed_count = ArcticWolfCompletion.objects.filter(
        user=user, course_id__in=eligible_aw_course_ids_for_current_user
    ).count()

    context = {
        "cmmc_courses_count": user_completed_trainings,
        "cmmc_total_courses_count": user_total_required_courses,  # User specific total (all tracked)
        "aw_completed_count": aw_completed_count,  # User specific completed (eligible only)
        "aw_total_courses_count": aw_total_courses_count,  # User specific total (eligible only)
        "total_possible_cmmc_trainings": total_possible_cmmc_trainings,
        "total_completed_cmmc_trainings": total_completed_cmmc_trainings,
        "uncompleted_cmmc_trainings": uncompleted_cmmc_trainings,
        "total_possible_aw_completions": total_possible_aw_completions,
        "total_actual_aw_completions": total_actual_aw_completions,
        "uncompleted_aw_completions": uncompleted_aw_completions,
        "is_superuser": request.user.is_superuser,
    }
    return render(request, "training/dashboard.html", context)


@login_required
def manage_matrix(request):
    accounts = Account.objects.all().order_by("type")
    courses = Course.objects.all().order_by("name")
    selected_account = None
    existing_matrix_entries = []
    frequency_choices = Matrix.FREQUENCY_CHOICES

    # Handle GET request for account selection
    if request.GET.get("account"):
        try:
            account_id = int(request.GET.get("account"))
            selected_account = get_object_or_404(Account, pk=account_id)
            existing_matrix_entries = Matrix.objects.filter(
                account=selected_account, is_active=True
            )
        except (ValueError, Account.DoesNotExist):
            messages.error(request, "Invalid account selected.")

    # Handle POST request for saving matrix
    if request.method == "POST" and request.POST.get("account"):
        try:
            selected_account = get_object_or_404(
                Account, pk=request.POST.get("account")
            )
            selected_courses = request.POST.getlist("selected_courses")

            # Soft-deactivate existing entries for this account
            Matrix.objects.filter(account=selected_account, is_active=True).update(
                is_active=False
            )

            # Create or reactivate entries
            for course_id in selected_courses:
                frequency = request.POST.get(f"frequency_{course_id}")
                if frequency:  # Only create if frequency is selected
                    Matrix.objects.update_or_create(
                        account=selected_account,
                        course_id=course_id,
                        defaults={"frequency": frequency, "is_active": True},
                    )

            messages.success(
                request,
                f"Training matrix updated for {selected_account.get_type_display()}",
            )
            return redirect("training:manage_matrix")

        except Exception as e:
            messages.error(request, f"Error saving matrix: {str(e)}")

    context = {
        "accounts": accounts,
        "courses": courses,
        "selected_account": selected_account,
        "existing_matrix_entries": existing_matrix_entries,
        "frequency_choices": frequency_choices,
    }

    return render(request, "training/manage_matrix.html", context)


@login_required
def user_training_requirements(request):
    user = request.user
    active_user_account_ids = UserAccount.objects.filter(user=user).values_list(
        "account_id", flat=True
    )
    required_matrix_entries = Matrix.objects.filter(
        account__in=active_user_account_ids,
        is_active=True,
    ).distinct()
    today = timezone.now().date()
    tracked_completions = (
        Tracker.objects.filter(user=user, matrix__in=required_matrix_entries)
        .select_related("matrix")
        .order_by("-completed_date", "-id")
    )
    completion_map = latest_completion_by_matrix(tracked_completions)

    required_courses_data = []
    for matrix_entry in required_matrix_entries:
        completion = completion_map.get(matrix_entry.id)
        is_current, expiration_date = get_completion_status(
            completion.completed_date if completion else None,
            matrix_entry.frequency,
            today,
        )
        required_courses_data.append(
            {
                "matrix_entry": matrix_entry,
                "completed": bool(completion),
                "is_current": is_current,
                "is_expired": bool(completion)
                and expiration_date
                and expiration_date < today,
                "expiration_date": expiration_date,
                "completion_date": completion.completed_date if completion else None,
                "document": completion.document if completion else None,
                "tracker_id": completion.id if completion else None,
                "document_name": completion.document_name if completion else None,
            }
        )

    context = {
        "required_courses_data": required_courses_data,
    }
    return render(request, "training/user_requirements.html", context)


@login_required
def review_course_link(request, matrix_id):
    """
    Log when a user clicks the course review link, then redirect to the actual URL.
    Records first and latest click timestamps for accountability.
    """
    matrix = get_object_or_404(Matrix, pk=matrix_id)

    # Ensure the user is associated with the matrix account (required course)
    if not UserAccount.objects.filter(
        user=request.user, account=matrix.account
    ).exists():
        messages.error(request, "You do not have access to this course link.")
        return redirect("training:user_requirements")

    if not matrix.course.link:
        messages.error(request, "No review link is available for this course.")
        return redirect("training:user_requirements")

    now = timezone.now()
    review_click, created = CourseReviewClick.objects.get_or_create(
        user=request.user,
        matrix=matrix,
        defaults={
            "first_clicked": now,
            "last_clicked": now,
        },
    )
    if not created:
        CourseReviewClick.objects.filter(pk=review_click.pk).update(last_clicked=now)

    return redirect(matrix.course.link)


@login_required
def mark_complete(request, course_id):
    if request.method == "POST":
        try:
            course = get_object_or_404(Course, pk=course_id)
            user = request.user
            active_user_account_ids = UserAccount.objects.filter(user=user).values_list(
                "account_id", flat=True
            )

            # Find the relevant Matrix entry for this user's account and the course
            matrix_entry = Matrix.objects.filter(
                account__in=active_user_account_ids,
                course=course,
                is_active=True,
            ).first()

            if matrix_entry:
                Tracker.objects.get_or_create(
                    user=user,
                    matrix=matrix_entry,
                    completed_date=timezone.now().date(),
                )
                messages.success(
                    request, f"Course '{course.name}' marked as completed."
                )
            else:
                messages.error(
                    request,
                    "No training requirement found for this course and your account.",
                )

        except Course.DoesNotExist:
            messages.error(request, "Invalid course.")
        return redirect("training:user_requirements")
    else:
        return redirect("training:user_requirements")


@login_required
def upload_document(request, matrix_id):  # Changed from matrix_entry_id to matrix_id
    if request.method == "POST" and request.FILES.get("document"):
        try:
            matrix = get_object_or_404(Matrix, pk=matrix_id)  # Changed to matrix
            tracker_entry = (
                Tracker.objects.filter(user=request.user, matrix=matrix)
                .order_by("-completed_date", "-id")
                .first()
            )
            if not tracker_entry:
                messages.error(request, "Completion record not found.")
                return redirect("training:user_requirements")
            uploaded_file = request.FILES["document"]

            tracker_entry.document = (
                uploaded_file.read()
            )  # Read the file content into binary data
            tracker_entry.document_name = get_valid_filename(uploaded_file.name)
            tracker_entry.save()
            messages.success(request, f"Document uploaded for '{matrix.course.name}'.")
        except Matrix.DoesNotExist:
            messages.error(request, "Invalid training requirement.")
        except Exception as e:
            messages.error(request, f"Error uploading document: {e}")

    return redirect("training:user_requirements")


@login_required
def view_document(request, tracker_id):
    try:
        tracker = get_object_or_404(Tracker, pk=tracker_id)
        if tracker.document:
            response = HttpResponse(
                tracker.document, content_type="application/octet-stream"
            )  # Generic binary type
            response["Content-Disposition"] = (
                f'inline; filename="{tracker.document_name}"'
            )
            return response
        else:
            return HttpResponse("No document uploaded.", status=204)  # No Content
    except Tracker.DoesNotExist:
        return HttpResponse("Document not found.", status=404)  # Not Found


@login_required
def training_audit(
    request,
):  # This audit is for non-staff users and is the CMMC training
    if not request.user.is_superuser:
        messages.error(request, "You do not have permission to view this audit.")
        return redirect("training:dashboard")

    users = User.objects.filter(is_active=True).order_by("username")
    courses = Course.objects.all().order_by("name")
    today = timezone.now().date()
    audit_data = []

    for user in users:
        user_accounts_qs = UserAccount.objects.filter(user=user).select_related(
            "account"
        )
        user_account_ids = [ua.account_id for ua in user_accounts_qs]
        account_labels = sorted(
            {ua.account.get_type_display() for ua in user_accounts_qs}
        )
        accounts_display = ", ".join(account_labels)
        required_matrix_entries = Matrix.objects.filter(
            account__in=user_account_ids,
            is_active=True,
        ).select_related("course")
        required_courses_for_user = {
            entry.course_id for entry in required_matrix_entries
        }
        frequency_by_course = {}
        for entry in required_matrix_entries:
            frequency_by_course[entry.course_id] = pick_strictest_frequency(
                frequency_by_course.get(entry.course_id),
                entry.frequency,
            )

        completions = (
            Tracker.objects.filter(user=user)
            .select_related("matrix")
            .order_by("-completed_date", "-id")
        )
        completion_dict = latest_completion_by_course(completions)
        user_row = {"user": user, "accounts_display": accounts_display, "courses": {}}

        for course in courses:
            is_required = course.id in required_courses_for_user
            completion_info = completion_dict.get(course.id)
            completed_date = completion_info.completed_date if completion_info else None
            has_document = bool(completion_info and completion_info.document)
            frequency = frequency_by_course.get(course.id)
            is_current, expiration_date = get_completion_status(
                completed_date, frequency, today
            )

            status = {
                "required": is_required,
                "completed_date": completed_date,
                "document": (
                    completion_info.document
                    if completion_info and has_document
                    else None
                ),
                "document_name": (
                    completion_info.document_name if completion_info else None
                ),
                "tracker_id": completion_info.id if completion_info else None,
                "is_current": is_current,
                "expiration_date": expiration_date,
            }
            user_row["courses"][course.id] = status
        audit_data.append(user_row)

    context = {
        "audit_data": audit_data,
        "courses": courses,
    }
    return render(request, "training/training_audit.html", context)


@login_required
def training_audit_export(request):
    """
    Export CMMC training audit as a PDF.
    Layout per user:
        Lastname, Firstname
            Course          Date Complete       Supporting Docs (If needed)
    Names are black, green indicates complete/good, red indicates not complete/bad.
    """
    if not request.user.is_superuser:
        messages.error(request, "You do not have permission to export this audit.")
        return redirect("training:dashboard")

    users = User.objects.filter(is_active=True).order_by("username")
    courses = Course.objects.all().order_by("name")

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    title = "Training Completion Audit"
    generated = timezone.now().strftime("%m/%d/%Y")
    today = timezone.now().date()

    def draw_page_header():
        p.setFont("Helvetica-Bold", 18)
        p.setFillColor(colors.black)
        p.drawString(50, height - 50, title)
        p.setFont("Helvetica", 10)
        p.drawString(50, height - 65, f"Generated on {generated}")

    draw_page_header()
    y = height - 90

    for user in users:
        user_accounts_qs = UserAccount.objects.filter(user=user).select_related(
            "account"
        )
        user_account_ids = [ua.account_id for ua in user_accounts_qs]
        account_labels = sorted(
            {ua.account.get_type_display() for ua in user_accounts_qs}
        )
        accounts_display = ", ".join(account_labels)
        required_matrix_entries = Matrix.objects.filter(
            account__in=user_account_ids,
            is_active=True,
        ).select_related("course")
        required_courses_for_user = {
            entry.course_id for entry in required_matrix_entries
        }
        frequency_by_course = {}
        for entry in required_matrix_entries:
            frequency_by_course[entry.course_id] = pick_strictest_frequency(
                frequency_by_course.get(entry.course_id),
                entry.frequency,
            )

        if not required_courses_for_user:
            continue

        completions = (
            Tracker.objects.filter(user=user)
            .select_related("matrix")
            .order_by("-completed_date", "-id")
        )
        completion_dict = latest_completion_by_course(completions)

        # Build list of required courses for this user
        user_courses = []
        for course in courses:
            if course.id not in required_courses_for_user:
                continue
            completion_info = completion_dict.get(course.id)
            completed_date = completion_info.completed_date if completion_info else None
            has_document = bool(completion_info and completion_info.document)
            frequency = frequency_by_course.get(course.id)
            is_current, _ = get_completion_status(completed_date, frequency, today)
            user_courses.append((course.name, completed_date, has_document, is_current))

        if not user_courses:
            continue

        # New page if needed before user header
        if y < 80:
            p.showPage()
            draw_page_header()
            y = height - 90

        # User header
        p.setFont("Helvetica-Bold", 12)
        p.setFillColor(colors.black)
        name_label = f"{user.last_name}, {user.first_name}"
        if accounts_display:
            name_label = f"{name_label} ({accounts_display})"
        p.drawString(50, y, name_label)
        y -= 14

        # Column headers
        p.setFont("Helvetica-Bold", 10)
        p.setFillColor(colors.black)
        p.drawString(70, y, "Course")
        p.drawString(320, y, "Date Complete")
        p.drawString(430, y, "Supporting Docs")
        y -= 12

        p.setFont("Helvetica", 9)

        for course_name, completed_date, has_document, is_current in user_courses:
            # New page in middle of user's courses
            if y < 50:
                p.showPage()
                draw_page_header()
                y = height - 80

                # Re-draw user and headers on new page
                p.setFont("Helvetica-Bold", 12)
                p.setFillColor(colors.black)
                p.drawString(50, y, f"{user.last_name}, {user.first_name}")
                y -= 14

                p.setFont("Helvetica-Bold", 10)
                p.setFillColor(colors.black)
                p.drawString(70, y, "Course")
                p.drawString(320, y, "Date Complete")
                p.drawString(430, y, "Supporting Docs")
                y -= 12

                p.setFont("Helvetica", 9)

            # Course name in black
            p.setFillColor(colors.black)
            p.drawString(70, y, course_name[:45])

            # Date column: green if current, red if not current
            if completed_date:
                date_text = completed_date.strftime("%m/%d/%Y")
                p.setFillColor(colors.green if is_current else colors.red)
            else:
                date_text = "Not Complete"
                p.setFillColor(colors.red)
            p.drawString(320, y, date_text)

            # Supporting docs: green check if document, red X otherwise
            if has_document:
                doc_text = "✓"
                p.setFillColor(colors.green)
            else:
                doc_text = "X"
                p.setFillColor(colors.red)
            p.drawString(440, y, doc_text)

            y -= 12

        y -= 10  # extra spacing between users

    p.showPage()
    p.save()

    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="training_audit.pdf"'
    buffer.close()
    return response


@login_required
def add_arctic_wolf_course(request):
    if request.method == "POST":
        form = ArcticWolfCourseForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect(
                "training:arctic_wolf_course_list"
            )  # Redirect to a list view (to be created)
    else:
        form = ArcticWolfCourseForm()
    return render(request, "training/add_arctic_wolf_course.html", {"form": form})


def arctic_wolf_course_list(request):
    # Courses list (most recent first)
    courses = ArcticWolfCourse.objects.all().order_by("-created_at", "name")

    # Count staff completions per course safely
    staff_completed = (
        ArcticWolfCompletion.objects.filter(
            user__is_active=True,
            user__is_staff=True,
            completed_date__isnull=False,
        )
        .values("course_id")
        .annotate(c=Count("id"))
    )
    completed_counts = {row["course_id"]: row["c"] for row in staff_completed}

    staff_total = User.objects.filter(is_active=True, is_staff=True).count()

    full_links = {}
    for course in courses:
        path = reverse(
            "training:arctic_wolf_training_completion", kwargs={"slug": course.slug}
        )
        full_links[course.slug] = request.build_absolute_uri(path)

    # Summary metrics and "new" marker
    now = timezone.now()
    new_since = now - timezone.timedelta(days=14)
    new_course_ids = {
        c.id for c in courses if c.created_at and c.created_at >= new_since
    }
    total_courses = len(courses)
    total_possible = staff_total * total_courses if staff_total and total_courses else 0
    total_completed = sum(completed_counts.get(c.id, 0) for c in courses)
    avg_completion_pct = (
        round((total_completed / total_possible) * 100) if total_possible else 0
    )

    context = {
        "courses": courses,
        "full_links": full_links,
        "staff_total": staff_total,
        "completed_counts": completed_counts,
        "total_courses": total_courses,
        "total_possible": total_possible,
        "total_completed": total_completed,
        "avg_completion_pct": avg_completion_pct,
        "new_course_ids": new_course_ids,
    }
    return render(request, "training/arctic_wolf_course_list.html", context)


def arctic_wolf_training_completion(request, slug):
    course = get_object_or_404(ArcticWolfCourse, slug=slug)
    completion = None
    if request.user.is_authenticated:
        completion = ArcticWolfCompletion.objects.filter(
            user=request.user, course=course
        ).first()

    return render(
        request,
        "training/arctic_wolf_completion.html",
        {"course": course, "completion": completion},
    )


@login_required
def arctic_wolf_complete_training(request, slug):
    course = get_object_or_404(ArcticWolfCourse, slug=slug)
    completion, created = ArcticWolfCompletion.objects.get_or_create(
        user=request.user,
        course=course,
        defaults={"completed_date": timezone.now().date()},
    )
    return render(
        request,
        "training/arctic_wolf_completion_status.html",
        {"course": course, "completion": completion},
    )


@login_required
def user_arctic_wolf_courses(request):
    all_courses = list(ArcticWolfCourse.objects.all().order_by("-created_at", "name"))
    eligible_course_ids = eligible_aw_course_ids_for_user(request.user, all_courses)
    courses = [course for course in all_courses if course.id in eligible_course_ids]
    completions = ArcticWolfCompletion.objects.filter(
        user=request.user, course_id__in=eligible_course_ids
    ).select_related("course")
    completed_courses = {
        completion.course_id: completion.completed_date for completion in completions
    }
    return render(
        request,
        "training/user_arctic_wolf_courses.html",
        {
            "courses": courses,
            "completed_courses": completed_courses,
        },
    )


@login_required
def arctic_wolf_audit(request):
    if not request.user.is_superuser:
        messages.error(request, "You do not have permission to view this audit.")
        return redirect("training:dashboard")

    six_months_ago = timezone.now().date() - timezone.timedelta(
        days=6 * 30
    )  # Approximate 6 months

    # Reference set: active staff users only (AW applies to staff)
    staff_users_qs = User.objects.filter(is_active=True, is_staff=True)
    active_users = list(staff_users_qs.order_by("username"))
    staff_count = len(active_users)
    user_by_id = {user.id: user for user in active_users}

    # Courses added in the last 6 months are always shown
    recent_courses = ArcticWolfCourse.objects.filter(
        created_at__date__gte=six_months_ago
    )

    # Older courses: include only those where not all eligible staff completed
    older_courses = list(
        ArcticWolfCourse.objects.filter(created_at__date__lt=six_months_ago)
    )
    older_ids_all = [c.id for c in older_courses]
    if older_ids_all:
        older_course_dates = {course.id: course.created_at for course in older_courses}
        older_eligible_counts = {
            course.id: sum(
                1
                for user in active_users
                if is_aw_course_required_for_user(
                    user, older_course_dates.get(course.id)
                )
            )
            for course in older_courses
        }
        older_completions = ArcticWolfCompletion.objects.filter(
            course_id__in=older_ids_all,
            user__in=staff_users_qs,
            completed_date__isnull=False,
        ).values("user_id", "course_id")
        older_counts_map = defaultdict(int)
        for row in older_completions:
            user = user_by_id.get(row["user_id"])
            course_date = older_course_dates.get(row["course_id"])
            if user and is_aw_course_required_for_user(user, course_date):
                older_counts_map[row["course_id"]] += 1
        older_ids = [
            cid
            for cid in older_ids_all
            if older_counts_map.get(cid, 0) < older_eligible_counts.get(cid, 0)
        ]
    else:
        older_ids = []

    recent_ids = list(recent_courses.values_list("id", flat=True))
    all_ids = list({*recent_ids, *older_ids})
    # Order audit courses most recent first
    courses = ArcticWolfCourse.objects.filter(id__in=all_ids).order_by(
        "-created_at", "name"
    )
    audit_data = []

    course_dates = {course.id: course.created_at for course in courses}
    eligible_user_ids_by_course = {
        course.id: {
            user.id
            for user in active_users
            if is_aw_course_required_for_user(user, course_dates.get(course.id))
        }
        for course in courses
    }

    completions = ArcticWolfCompletion.objects.filter(
        user__in=staff_users_qs,
        course__in=courses,
    ).values("user_id", "course_id", "completed_date")
    completion_map = {
        (row["user_id"], row["course_id"]): row["completed_date"] for row in completions
    }

    for user in active_users:
        user_data = {"user": user, "courses": {}}
        for course in courses:
            completed_date = completion_map.get((user.id, course.id))
            not_required = user.id not in eligible_user_ids_by_course.get(
                course.id, set()
            )
            user_data["courses"][course.id] = {
                "completed_date": completed_date,
                "not_required": not_required,
            }
        audit_data.append(user_data)

    # Per-course completion counts for UI (to hide fully complete columns if desired)
    column_completed_counts = defaultdict(int)
    for row in completions:
        if row["completed_date"] and row["user_id"] in eligible_user_ids_by_course.get(
            row["course_id"], set()
        ):
            column_completed_counts[row["course_id"]] += 1

    eligible_counts_by_course = {
        course.id: len(eligible_user_ids_by_course.get(course.id, set()))
        for course in courses
    }

    context = {
        "courses": courses,
        "audit_data": audit_data,
        "users_count": staff_count,
        "overdue_course_ids": older_ids,
        "column_completed_counts": dict(column_completed_counts),
        "eligible_counts_by_course": eligible_counts_by_course,
    }
    return render(request, "training/arctic_wolf_audit.html", context)


@login_required
def arctic_wolf_audit_export(request):
    """
    Export Arctic Wolf training audit as a PDF.
    Layout per user:
        Lastname, Firstname
            Course          Date Complete       Supporting Docs (If needed)
    Names are black, green indicates complete/good, red indicates not complete/bad.
    Supporting Docs column is used as a completion check mark for AW.
    """
    if not request.user.is_superuser:
        messages.error(request, "You do not have permission to export this audit.")
        return redirect("training:dashboard")

    six_months_ago = timezone.now().date() - timezone.timedelta(days=6 * 30)

    staff_users_qs = User.objects.filter(is_active=True, is_staff=True)
    active_users = list(staff_users_qs.order_by("username"))
    user_by_id = {user.id: user for user in active_users}

    recent_courses = ArcticWolfCourse.objects.filter(
        created_at__date__gte=six_months_ago
    )

    older_courses = list(
        ArcticWolfCourse.objects.filter(created_at__date__lt=six_months_ago)
    )
    older_ids_all = [c.id for c in older_courses]
    if older_ids_all:
        older_course_dates = {course.id: course.created_at for course in older_courses}
        older_eligible_counts = {
            course.id: sum(
                1
                for user in active_users
                if is_aw_course_required_for_user(
                    user, older_course_dates.get(course.id)
                )
            )
            for course in older_courses
        }
        older_completions = ArcticWolfCompletion.objects.filter(
            course_id__in=older_ids_all,
            user__in=staff_users_qs,
            completed_date__isnull=False,
        ).values("user_id", "course_id")
        older_counts_map = defaultdict(int)
        for row in older_completions:
            user = user_by_id.get(row["user_id"])
            course_date = older_course_dates.get(row["course_id"])
            if user and is_aw_course_required_for_user(user, course_date):
                older_counts_map[row["course_id"]] += 1
        older_ids = [
            cid
            for cid in older_ids_all
            if older_counts_map.get(cid, 0) < older_eligible_counts.get(cid, 0)
        ]
    else:
        older_ids = []

    recent_ids = list(recent_courses.values_list("id", flat=True))
    all_ids = list({*recent_ids, *older_ids})
    courses = ArcticWolfCourse.objects.filter(id__in=all_ids).order_by(
        "-created_at", "name"
    )

    course_dates = {course.id: course.created_at for course in courses}

    # Pre-fetch completions to reduce queries
    completions = ArcticWolfCompletion.objects.filter(
        user__in=active_users,
        course__in=courses,
    ).values("user_id", "course_id", "completed_date")
    completion_map = {}
    for row in completions:
        completion_map[(row["user_id"], row["course_id"])] = row["completed_date"]

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    title = "Arctic Wolf Training Audit"
    generated = timezone.now().strftime("%m/%d/%Y")

    def draw_page_header():
        p.setFont("Helvetica-Bold", 18)
        p.setFillColor(colors.black)
        p.drawString(50, height - 50, title)
        p.setFont("Helvetica", 10)
        p.drawString(50, height - 65, f"Generated on {generated}")

    draw_page_header()
    y = height - 90

    for user in active_users:
        # Build list of all AW audit courses for this user
        user_courses = []
        for course in courses:
            completed_date = completion_map.get((user.id, course.id))
            not_required = not is_aw_course_required_for_user(
                user, course_dates.get(course.id)
            )
            user_courses.append((course.name, completed_date, not_required))

        if not user_courses:
            continue

        if y < 80:
            p.showPage()
            draw_page_header()
            y = height - 90

        # User header
        p.setFont("Helvetica-Bold", 12)
        p.setFillColor(colors.black)
        p.drawString(50, y, f"{user.last_name}, {user.first_name}")
        y -= 14

        # Column headers
        p.setFont("Helvetica-Bold", 10)
        p.setFillColor(colors.black)
        p.drawString(70, y, "Course")
        p.drawString(320, y, "Date Complete")
        p.drawString(430, y, "Supporting Docs")
        y -= 12

        p.setFont("Helvetica", 9)

        for course_name, completed_date, not_required in user_courses:
            if y < 50:
                p.showPage()
                draw_page_header()
                y = height - 80

                p.setFont("Helvetica-Bold", 12)
                p.setFillColor(colors.black)
                p.drawString(50, y, f"{user.last_name}, {user.first_name}")
                y -= 14

                p.setFont("Helvetica-Bold", 10)
                p.setFillColor(colors.black)
                p.drawString(70, y, "Course")
                p.drawString(320, y, "Date Complete")
                p.drawString(430, y, "Supporting Docs")
                y -= 12

                p.setFont("Helvetica", 9)

            # Course name in black
            p.setFillColor(colors.black)
            p.drawString(70, y, course_name[:45])

            # Date column: gray if not required, green if complete, red if not
            if not_required:
                date_text = "Not Required"
                p.setFillColor(colors.gray)
            elif completed_date:
                date_text = completed_date.strftime("%m/%d/%Y")
                p.setFillColor(colors.green)
            else:
                date_text = "Not Complete"
                p.setFillColor(colors.red)
            p.drawString(320, y, date_text)

            # Supporting docs column used as completion checkmark
            if not_required:
                doc_text = "-"
                p.setFillColor(colors.gray)
            elif completed_date:
                doc_text = "✓"
                p.setFillColor(colors.green)
            else:
                doc_text = "X"
                p.setFillColor(colors.red)
            p.drawString(440, y, doc_text)

            y -= 12

        y -= 10

    p.showPage()
    p.save()

    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="arctic_wolf_audit.pdf"'
    buffer.close()
    return response


@login_required
def arctic_wolf_email_preview(request, slug):
    """Render a preview of the email to send to users for a given course.
    This mimics the Arctic Wolf email, but uses our completion link and
    replaces the Start CTA with a Sign CTA.
    """
    course = get_object_or_404(ArcticWolfCourse, slug=slug)
    path = reverse(
        "training:arctic_wolf_training_completion", kwargs={"slug": course.slug}
    )
    full_link = request.build_absolute_uri(path)

    # Optional audience name in greeting (defaults to Team)
    audience = request.GET.get("audience") or "Team"

    context = {
        "course": course,
        "full_link": full_link,
        "audience": audience,
        "subject": f"Today's Security Awareness Session: {course.name}",
    }
    return render(request, "training/arctic_wolf_email.html", context)


@login_required
def arctic_wolf_email_eml(request, slug):
    """Generate a downloadable .eml file for the given course using the HTML body template.
    The EML is a simple message with Subject and HTML body, leaving To/From blank
    so Outlook can fill as appropriate when opened.
    """
    from email.message import EmailMessage
    from email.utils import formatdate, make_msgid
    from email.policy import SMTP

    course = get_object_or_404(ArcticWolfCourse, slug=slug)
    path = reverse(
        "training:arctic_wolf_training_completion", kwargs={"slug": course.slug}
    )
    full_link = request.build_absolute_uri(path)
    audience = request.GET.get("audience") or "Team"

    subject = f"Today's Security Awareness Session: {course.name}"
    html = render_to_string(
        "training/arctic_wolf_email_body.html",
        {
            "course": course,
            "full_link": full_link,
            "audience": audience,
        },
    )

    msg = EmailMessage(policy=SMTP)
    # Hint Outlook to open this .eml as a new, unsent draft instead of a received message
    msg["X-Unsent"] = "1"
    msg["Content-Class"] = "urn:content-classes:message"
    msg["Subject"] = subject
    # Intentionally do NOT set From; Outlook will use the current user's account
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=None)
    # Plain-text alternative for compatibility
    plain_text = (
        f"Hello {audience},\n"
        f"It's time for another security awareness session.\n"
        f"Today's session is: {course.name}\n"
        f"Duration: Less than 5 minutes\n"
        f"We appreciate your participation in the program. Keeping everyone up to date with these topics is very important to our cybersecurity.\n"
        f'When you\'re ready, click the "Sign" link:\n{full_link}\n\n'
        f"Thank you,\n"
        f"Arctic Wolf Managed Security Awareness Team\n\n"
        f"---\n\n"
        f"Hola {audience},\n"
        f"Es hora de otra sesion de concienciacion sobre seguridad.\n"
        f"La sesion de hoy es: {course.name}\n"
        f"Duracion: Less than 5 minutes\n"
        f"Agradecemos su participacion en el programa. Mantener a todos al dia sobre estos temas es muy importante para nuestra seguridad cibernetica.\n"
        f'Cuando este listo, haga clic en el enlace "Sign":\n{full_link}\n\n'
        f"Muchas gracias,"
        f"Arctic Wolf Managed Security Awareness Team\n\n"
        f"---\n\n"
        f"Hallo {audience},\n"
        f"Es ist Zeit fuer eine weitere Schulung zum Thema 'Security Awareness'.\n"
        f"Das heutige Thema heisst: {course.name}\n"
        f"Dauer: Less than 5 minutes\n"
        f"Wir freuen uns ueber Ihre Teilnahme. Es ist fuer unsere IT-Sicherheit sehr wichtig, dass alle ueber diese Themen auf dem Laufenden sind.\n"
        f"Klicken Sie jetzt auf den Link 'Sign', wenn Sie bereit sind:\n{full_link}\n\n"
        f"Vielen Dank,"
        f"Arctic Wolf Managed Security Awareness Team\n"
    )
    msg.set_content(plain_text)
    msg.add_alternative(html, subtype="html")

    eml_bytes = msg.as_bytes()
    filename = f"aw-session-{course.slug}.eml"
    response = HttpResponse(eml_bytes, content_type="message/rfc822")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def admin_cmmc_upload(request):
    """
    Administrator view for uploading CMMC training documents.
    Restricted to staff users only.
    """
    if not request.user.is_staff:
        messages.error(request, "You do not have permission to access this page.")
        return redirect("training:dashboard")

    if request.method == "POST":
        form = CmmcDocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                user = form.cleaned_data["user"]
                course = form.cleaned_data["course"]
                uploaded_file = form.cleaned_data.get("file")

                # Find the relevant Matrix entry for this user/course combination
                user_accounts = UserAccount.objects.filter(user=user).values_list(
                    "account_id", flat=True
                )
                matrix_entry = Matrix.objects.filter(
                    account__in=user_accounts,
                    course=course,
                    is_active=True,
                ).first()

                if not matrix_entry:
                    messages.error(
                        request,
                        "No valid matrix entry found for the selected user/course combination.",
                    )

                if not uploaded_file:
                    form.add_error("file", "This field is required.")

                if matrix_entry and uploaded_file:
                    # Create or update the Tracker entry for today's completion
                    today = timezone.now().date()
                    tracker_entry = (
                        Tracker.objects.filter(
                            user=user, matrix=matrix_entry, completed_date=today
                        )
                        .order_by("-id")
                        .first()
                    )
                    created = False
                    if not tracker_entry:
                        tracker_entry = Tracker.objects.create(
                            user=user,
                            matrix=matrix_entry,
                            completed_date=today,
                        )
                        created = True

                    # Store the uploaded file
                    tracker_entry.document = uploaded_file.read()
                    tracker_entry.document_name = get_valid_filename(uploaded_file.name)
                    tracker_entry.save()

                    action = "created" if created else "updated"
                    messages.success(
                        request,
                        f"Document successfully {action} for {user.get_full_name() or user.username} - {course.name}",
                    )
                    return redirect("training:admin_cmmc_upload")

            except Exception as e:
                messages.error(request, f"Error uploading document: {str(e)}")
        else:
            if form.non_field_errors():
                messages.error(
                    request,
                    "No valid matrix entry found for the selected user/course combination.",
                )
    else:
        form = CmmcDocumentUploadForm()

    # Get existing uploads for context (optional display)
    existing_uploads = (
        Tracker.objects.filter(document__isnull=False)
        .select_related("user", "matrix__course")
        .order_by("-completed_date")[:10]
    )

    account_courses = defaultdict(dict)
    for entry in (
        Matrix.objects.filter(is_active=True)
        .select_related("course")
        .values("account_id", "course_id", "course__name")
    ):
        account_courses[entry["account_id"]][entry["course_id"]] = entry["course__name"]

    user_course_map = defaultdict(dict)
    for user_id, account_id in UserAccount.objects.values_list("user_id", "account_id"):
        for course_id, course_name in account_courses.get(account_id, {}).items():
            user_course_map[user_id][course_id] = course_name

    user_course_map_json = json.dumps(
        {
            str(user_id): [
                {"id": course_id, "name": course_name}
                for course_id, course_name in sorted(
                    courses.items(), key=lambda item: item[1].lower()
                )
            ]
            for user_id, courses in user_course_map.items()
        }
    )

    context = {
        "form": form,
        "existing_uploads": existing_uploads,
        "user_course_map_json": user_course_map_json,
    }
    return render(request, "training/admin_cmmc_upload.html", context)
