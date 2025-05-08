from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .forms import MatrixManagementForm, ArcticWolfCourseForm
from .models import Matrix, Account, Course, UserAccount, Tracker, ArcticWolfCourse, ArcticWolfCompletion
from django.utils import timezone
from django.core.files.base import ContentFile
from django.utils.text import get_valid_filename
from django.http import HttpResponse
from django.contrib.auth.models import User
from django.urls import reverse

@login_required
def dashboard(request):
    total_courses = Course.objects.all().count()
    total_completed_trainings = Tracker.objects.filter(user=request.user, completed_date__isnull=False).count()
    arctic_wolf_courses = ArcticWolfCourse.objects.all().count()
    arctic_wolf_completed = ArcticWolfCompletion.objects.filter(user=request.user).count()

    context = {
        'cmmc_courses_count': total_courses,  # Renamed for clarity
        'cmmc_completed_count': total_completed_trainings,  # Renamed for clarity
        'arctic_wolf_courses_count': arctic_wolf_courses,
        'arctic_wolf_completed_count': arctic_wolf_completed,
        'is_staff': request.user.is_staff,
    }
    return render(request, 'training/dashboard.html', context)

@login_required
def manage_matrix(request):
    accounts = Account.objects.all().order_by('type')
    courses = Course.objects.all().order_by('name')
    selected_account = None
    existing_matrix_entries = []
    frequency_choices = Matrix.FREQUENCY_CHOICES

    # Handle GET request for account selection
    if request.GET.get('account'):
        try:
            account_id = int(request.GET.get('account'))
            selected_account = get_object_or_404(Account, pk=account_id)
            existing_matrix_entries = Matrix.objects.filter(account=selected_account)
        except (ValueError, Account.DoesNotExist):
            messages.error(request, "Invalid account selected.")
    
    # Handle POST request for saving matrix
    if request.method == 'POST' and request.POST.get('account'):
        try:
            selected_account = get_object_or_404(Account, pk=request.POST.get('account'))
            selected_courses = request.POST.getlist('selected_courses')
            
            # Delete existing entries for this account
            Matrix.objects.filter(account=selected_account).delete()
            
            # Create new entries
            for course_id in selected_courses:
                frequency = request.POST.get(f'frequency_{course_id}')
                if frequency:  # Only create if frequency is selected
                    Matrix.objects.create(
                        account=selected_account,
                        course_id=course_id,
                        frequency=frequency
                    )
            
            messages.success(request, f"Training matrix updated for {selected_account.get_type_display()}")
            return redirect('training:manage_matrix')
            
        except Exception as e:
            messages.error(request, f"Error saving matrix: {str(e)}")
    
    context = {
        'accounts': accounts,
        'courses': courses,
        'selected_account': selected_account,
        'existing_matrix_entries': existing_matrix_entries,
        'frequency_choices': frequency_choices,
    }
    
    return render(request, 'training/manage_matrix.html', context)


@login_required
def user_training_requirements(request):
    user = request.user
    active_user_accounts = UserAccount.objects.filter(user=user)
    required_matrix_entries = Matrix.objects.filter(account__in=[ua.account for ua in active_user_accounts]).distinct()
    tracked_completions = Tracker.objects.filter(user=user)

    required_courses_data = []
    for matrix_entry in required_matrix_entries:
        completion = tracked_completions.filter(matrix=matrix_entry).first()
        required_courses_data.append({
            'matrix_entry': matrix_entry,
            'completed': bool(completion),
            'completion_date': completion.completed_date if completion else None,
            'document': completion.document if completion else None,
            'tracker_id': completion.id if completion else None,
            'document_name': completion.document_name if completion else None,
        })

    context = {
        'required_courses_data': required_courses_data,
    }
    return render(request, 'training/user_requirements.html', context)

@login_required
def mark_complete(request, course_id):
    if request.method == 'POST':
        try:
            course = get_object_or_404(Course, pk=course_id)
            user = request.user
            active_user_accounts = UserAccount.objects.filter(user=user)

            # Find the relevant Matrix entry for this user's account and the course
            matrix_entry = Matrix.objects.filter(account__in=[ua.account for ua in active_user_accounts], course=course).first()

            if matrix_entry:
                Tracker.objects.get_or_create(user=user, matrix=matrix_entry, completed_date=timezone.now())
                messages.success(request, f"Course '{course.name}' marked as completed.")
            else:
                messages.error(request, "No training requirement found for this course and your account.")

        except Course.DoesNotExist:
            messages.error(request, "Invalid course.")
        return redirect('training:user_requirements')
    else:
        return redirect('training:user_requirements')
    
@login_required
def upload_document(request, matrix_id):  # Changed from matrix_entry_id to matrix_id
    if request.method == 'POST' and request.FILES.get('document'):
        try:
            matrix = get_object_or_404(Matrix, pk=matrix_id) # Changed to matrix
            tracker_entry = Tracker.objects.get(user=request.user, matrix=matrix)
            uploaded_file = request.FILES['document']

            tracker_entry.document = uploaded_file.read()  # Read the file content into binary data
            tracker_entry.document_name = get_valid_filename(uploaded_file.name)
            tracker_entry.save()
            messages.success(request, f"Document uploaded for '{matrix.course.name}'.")
        except Matrix.DoesNotExist:
            messages.error(request, "Invalid training requirement.")
        except Tracker.DoesNotExist:
            messages.error(request, "Completion record not found.")
        except Exception as e:
            messages.error(request, f"Error uploading document: {e}")

    return redirect('training:user_requirements')

@login_required
def view_document(request, tracker_id):
    try:
        tracker = get_object_or_404(Tracker, pk=tracker_id)
        if tracker.document:
            response = HttpResponse(tracker.document, content_type='application/octet-stream')  # Generic binary type
            response['Content-Disposition'] = f'inline; filename="{tracker.document_name}"'
            return response
        else:
            return HttpResponse("No document uploaded.", status=204) # No Content
    except Tracker.DoesNotExist:
        return HttpResponse("Document not found.", status=404) # Not Found
    

@login_required
def training_audit(request):
    users = User.objects.filter(is_active=True).order_by('username')
    courses = Course.objects.all().order_by('name')
    audit_data = []

    for user in users:
        user_accounts = UserAccount.objects.filter(user=user).values_list('account_id', flat=True)
        user_completion_status = Tracker.objects.filter(user=user).values('matrix__course_id', 'completed_date', 'document', 'document_name', 'id')
        required_courses_for_user = Matrix.objects.filter(account__in=user_accounts).values_list('course_id', flat=True).distinct()

        completion_dict = {item['matrix__course_id']: item for item in user_completion_status}
        user_row = {'user': user, 'courses': {}}

        for course in courses:
            is_required = course.id in required_courses_for_user
            completion_info = completion_dict.get(course.id)

            status = {
                'required': is_required,
                'completed_date': completion_info['completed_date'] if completion_info else None,
                'document': completion_info['document'] if completion_info else None,
                'document_name': completion_info['document_name'] if completion_info else None,
                'tracker_id': completion_info['id'] if completion_info else None,
            }
            user_row['courses'][course.id] = status
        audit_data.append(user_row)

    context = {
        'audit_data': audit_data,
        'courses': courses,
    }
    return render(request, 'training/training_audit.html', context)

@login_required
def add_arctic_wolf_course(request):
    if request.method == 'POST':
        form = ArcticWolfCourseForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('training:arctic_wolf_course_list') # Redirect to a list view (to be created)
    else:
        form = ArcticWolfCourseForm()
    return render(request, 'training/add_arctic_wolf_course.html', {'form': form})

def arctic_wolf_course_list(request):
    courses = ArcticWolfCourse.objects.all().order_by('name')
    full_links = {}
    for course in courses:
        path = reverse('training:arctic_wolf_training_completion', kwargs={'slug': course.slug})
        full_links[course.slug] = request.build_absolute_uri(path)
    return render(request, 'training/arctic_wolf_course_list.html', {'courses': courses, 'full_links': full_links})


def arctic_wolf_training_completion(request, slug):
    course = get_object_or_404(ArcticWolfCourse, slug=slug)
    completion = None
    if request.user.is_authenticated:
        completion = ArcticWolfCompletion.objects.filter(user=request.user, course=course).first()

    return render(request, 'training/arctic_wolf_completion.html', {'course': course, 'completion': completion})

@login_required
def arctic_wolf_complete_training(request, slug):
    course = get_object_or_404(ArcticWolfCourse, slug=slug)
    completion, created = ArcticWolfCompletion.objects.get_or_create(
        user=request.user,
        course=course,
        defaults={'completed_date': timezone.now().date()}
    )
    return render(request, 'training/arctic_wolf_completion_status.html', {'course': course, 'completion': completion})

@login_required
def user_arctic_wolf_courses(request):
    courses = ArcticWolfCourse.objects.all().order_by('name')
    completions = ArcticWolfCompletion.objects.filter(user=request.user).select_related('course')
    completed_courses = {completion.course_id: completion.completed_date for completion in completions}
    return render(request, 'training/user_arctic_wolf_courses.html', {
        'courses': courses,
        'completed_courses': completed_courses,
    })


@login_required
def arctic_wolf_audit(request):
    six_months_ago = timezone.now().date() - timezone.timedelta(days=6 * 30)  # Approximate 6 months

    # Get courses added in the last 6 months
    recent_courses = ArcticWolfCourse.objects.filter(created_at__date__gte=six_months_ago)

    # Get older courses that are missing by at least one active user
    all_active_users = User.objects.filter(is_active=True)
    older_courses = ArcticWolfCourse.objects.filter(created_at__date__lt=six_months_ago).exclude(
        arcticwolfcompletion__user__in=all_active_users,
        arcticwolfcompletion__completed_date__isnull=False
    ).distinct()

    courses = recent_courses.union(older_courses).order_by('name')
    active_users = User.objects.filter(is_active=True).order_by('username')
    audit_data = []

    for user in active_users:
        user_completions = ArcticWolfCompletion.objects.filter(user=user).values_list('course_id', flat=True)
        user_data = {'user': user, 'courses': {}}
        for course in courses:
            completed = ArcticWolfCompletion.objects.filter(user=user, course=course).first()
            user_data['courses'][course.id] = completed.completed_date if completed else None
        audit_data.append(user_data)

    context = {
        'courses': courses,
        'audit_data': audit_data,
    }
    return render(request, 'training/arctic_wolf_audit.html', context)