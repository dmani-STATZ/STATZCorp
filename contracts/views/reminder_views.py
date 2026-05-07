from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse, HttpResponseRedirect
from django.utils import timezone
from django.db.models import Q
from django.core.paginator import Paginator
from datetime import timedelta

from STATZWeb.decorators import conditional_login_required
from ..models import Reminder, Note
from ..forms import ReminderForm


def _request_is_ajax(request):
    """True for fetch/XHR from the reminders popup (tolerates header casing)."""
    v = request.headers.get('x-requested-with') or request.META.get('HTTP_X_REQUESTED_WITH', '')
    return (v or '').lower() == 'xmlhttprequest'


@conditional_login_required
def add_reminder(request, note_id=None):
    note = None
    if note_id:
        note = get_object_or_404(Note, id=note_id)
    
    if request.method == 'POST':
        form = ReminderForm(request.POST)
        if form.is_valid():
            reminder = form.save(commit=False)
            reminder.reminder_user = request.user
            # Set company from note or active company
            if note and hasattr(note, 'company') and note.company_id:
                reminder.company_id = note.company_id
            elif getattr(request, 'active_company', None):
                reminder.company = request.active_company
            
            if note:
                reminder.note = note
            
            reminder.save()
            
            messages.success(request, 'Reminder added successfully.')
            
            # Determine the redirect URL
            if note and note.content_type.model == 'contract':
                redirect_url = reverse('contracts:contract_management', kwargs={'pk': note.object_id})
            elif note and note.content_type.model == 'clin':
                redirect_url = reverse('contracts:clin_detail', kwargs={'pk': note.object_id})
            else:
                redirect_url = reverse('contracts:reminders_list')
            
            return HttpResponseRedirect(redirect_url)
    else:
        initial = {}
        if note:
            initial['reminder_text'] = f"Follow up on note: {note.note[:50]}..."
        
        form = ReminderForm(initial=initial)
    
    return render(request, 'contracts/reminder_form.html', {
        'form': form,
        'note': note
    })


# Create an alias for add_reminder to support the create_reminder URL pattern
create_reminder = add_reminder


class ReminderListView(ListView):
    model = Reminder
    template_name = 'contracts/reminders_list.html'
    context_object_name = 'reminders_page'
    
    def get_queryset(self):
        # Get reminders for the current user
        user = self.request.user
        
        # Base queryset - reminders assigned to the user
        queryset = Reminder.objects.filter(
            reminder_user=user
        ).select_related(
            'reminder_user', 'reminder_completed_user', 'note'
        ).order_by('reminder_date')
        # Scope by company if available
        if getattr(self.request, 'active_company', None):
            queryset = queryset.filter(company=self.request.active_company)
        
        # Default to all pending on a fresh visit (no query params) — matches popup + pill.
        status_filter = self.request.GET.get('status')
        due_filter = self.request.GET.get('due')
        if due_filter is None and status_filter is None:
            status_filter = 'pending'

        # Filter by completion status
        if status_filter == 'completed':
            queryset = queryset.filter(reminder_completed=True)
        elif status_filter == 'pending':
            queryset = queryset.filter(Q(reminder_completed=False) | Q(reminder_completed__isnull=True))

        # Filter by due date. 'all' is the sentinel value that means "no due filter".
        today = timezone.now().date()
        seven_days_ago = today - timedelta(days=7)

        if due_filter == 'overdue':
            # Overdue: reminder_date <= today-7days
            queryset = queryset.filter(
                reminder_date__lte=seven_days_ago,
                reminder_completed=False
            )
        elif due_filter == 'due':
            # Due: reminder_date <= today AND reminder_date > today-7days
            queryset = queryset.filter(
                reminder_date__lte=today,
                reminder_date__gt=seven_days_ago,
                reminder_completed=False
            )
        elif due_filter == 'upcoming':
            # Future/Pending: reminder_date > today
            queryset = queryset.filter(
                reminder_date__gt=today,
                reminder_completed=False
            )

        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.now().date()
        seven_days_ago = today - timedelta(days=7)
        
        # Add filter parameters to context, applying the same default as get_queryset.
        status_param = self.request.GET.get('status')
        due_param = self.request.GET.get('due')
        if due_param is None and status_param is None:
            status_param = 'pending'
        context['status_filter'] = status_param or ''
        context['due_filter'] = due_param or ''
        
        # Add counts for different reminder categories
        all_reminders = Reminder.objects.filter(reminder_user=user)
        if getattr(self.request, 'active_company', None):
            all_reminders = all_reminders.filter(company=self.request.active_company)
        
        context['total_count'] = all_reminders.count()
        context['completed_count'] = all_reminders.filter(reminder_completed=True).count()
        
        # Get non-completed reminders
        active_reminders = all_reminders.filter(
            Q(reminder_completed=False) | Q(reminder_completed__isnull=True)
        )
        context['pending_count'] = active_reminders.count()
        
        # Overdue: reminder_date <= today-7days
        context['overdue_count'] = active_reminders.filter(
            reminder_date__lte=seven_days_ago
        ).count()
        
        # Due: reminder_date <= today AND reminder_date > today-7days
        context['due_count'] = active_reminders.filter(
            reminder_date__lte=today,
            reminder_date__gt=seven_days_ago
        ).count()
        
        # Future/Pending: reminder_date > today
        context['upcoming_count'] = active_reminders.filter(
            reminder_date__gt=today
        ).count()
        
        # Add seven_days_ago to context for template use
        context['seven_days_ago'] = seven_days_ago
        context['today'] = today
        
        # Process reminders to add is_overdue flag
        for reminder in context['reminders_page']:
            reminder.is_overdue = reminder.reminder_date <= seven_days_ago
        
        return context


def _pending_reminder_q():
    return Q(reminder_completed=False) | Q(reminder_completed__isnull=True)


def _annotate_popup_reminder(reminder, today):
    """Card chrome: footer-aligned overdue (before today) vs due today vs upcoming."""
    done = bool(reminder.reminder_completed)
    reminder.is_footer_overdue = (not done and reminder.reminder_date < today)
    reminder.is_due_today = (not done and reminder.reminder_date == today)
    reminder.is_upcoming_card = (not done and reminder.reminder_date > today)


@conditional_login_required
def reminders_popup(request):
    """
    Bare-chrome reminders window opened via window.open() from the footer pill.
    Default: overdue + due today (non-completed), matching footer badge counts.
    ?due=all&status=pending — all non-completed, due ASC, paginated (50).
    """
    user = request.user
    today = timezone.now().date()
    seven_days_ago = today - timedelta(days=7)

    queryset = Reminder.objects.filter(
        reminder_user=user
    ).select_related(
        'reminder_user', 'reminder_completed_user', 'note', 'note__content_type'
    )

    if getattr(request, 'active_company', None):
        queryset = queryset.filter(company=request.active_company)

    status_param = request.GET.get('status')
    due_param = request.GET.get('due')
    if due_param is None and status_param is None:
        due_param = 'due_and_overdue'

    status_filter = (status_param or '').strip()
    due_filter = (due_param or '').strip()

    paginate = False
    view_mode = 'due_now'

    if status_filter == 'completed':
        queryset = queryset.filter(reminder_completed=True).order_by('-reminder_date', '-id')
        view_mode = 'completed'
    elif due_filter == 'due_and_overdue':
        queryset = queryset.filter(
            reminder_date__lte=today,
        ).filter(_pending_reminder_q()).order_by('reminder_date', 'id')
        view_mode = 'due_now'
    elif due_filter == 'overdue':
        queryset = queryset.filter(
            reminder_date__lte=seven_days_ago,
        ).filter(_pending_reminder_q()).order_by('reminder_date', 'id')
        view_mode = 'due_now'
    elif due_filter == 'due':
        queryset = queryset.filter(
            reminder_date__lte=today,
            reminder_date__gt=seven_days_ago,
        ).filter(_pending_reminder_q()).order_by('reminder_date', 'id')
        view_mode = 'due_now'
    elif due_filter == 'upcoming':
        queryset = queryset.filter(reminder_date__gt=today).filter(_pending_reminder_q()).order_by(
            'reminder_date', 'id'
        )
        view_mode = 'all_pending'
    elif due_filter == 'all' or status_filter == 'pending':
        queryset = queryset.filter(_pending_reminder_q()).order_by('reminder_date', 'id')
        paginate = True
        view_mode = 'all_pending'
    else:
        queryset = queryset.filter(
            reminder_date__lte=today,
        ).filter(_pending_reminder_q()).order_by('reminder_date', 'id')
        due_filter = 'due_and_overdue'
        view_mode = 'due_now'

    all_reminders = Reminder.objects.filter(reminder_user=user)
    if getattr(request, 'active_company', None):
        all_reminders = all_reminders.filter(company=request.active_company)

    active_reminders = all_reminders.filter(_pending_reminder_q())

    footer_overdue_count = active_reminders.filter(reminder_date__lt=today).count()
    footer_due_today_count = active_reminders.filter(reminder_date=today).count()

    pagination_base_query = ''
    page_obj = None
    is_paginated = False

    if paginate:
        paginator = Paginator(queryset, 50)
        page_number = request.GET.get('page') or 1
        page_obj = paginator.get_page(page_number)
        for reminder in page_obj.object_list:
            _annotate_popup_reminder(reminder, today)
        get_params = request.GET.copy()
        get_params.pop('page', None)
        pagination_base_query = get_params.urlencode()
        reminders_iterable = page_obj
        is_paginated = paginator.num_pages > 1
    else:
        reminders_list = list(queryset)
        for reminder in reminders_list:
            _annotate_popup_reminder(reminder, today)
        reminders_iterable = reminders_list

    context = {
        'reminders': reminders_iterable,
        'page_obj': page_obj,
        'is_paginated': is_paginated,
        'pagination_base_query': pagination_base_query,
        'status_filter': status_filter,
        'due_filter': due_filter,
        'view_mode': view_mode,
        'total_count': all_reminders.count(),
        'completed_count': all_reminders.filter(reminder_completed=True).count(),
        'pending_count': active_reminders.count(),
        'footer_overdue_count': footer_overdue_count,
        'footer_due_today_count': footer_due_today_count,
        'today': today,
        'seven_days_ago': seven_days_ago,
    }

    return render(request, 'contracts/reminders_popup.html', context)


@conditional_login_required
def reminders_popup_add(request):
    """
    Handles the New Reminder form POST from the popup window.
    On success redirects back to the popup window (not the main reminders_list).
    On GET, redirects to the popup window (the modal opens from there).
    """
    if request.method == 'POST':
        form = ReminderForm(request.POST)
        if form.is_valid():
            reminder = form.save(commit=False)
            reminder.reminder_user = request.user
            if getattr(request, 'active_company', None):
                reminder.company = request.active_company
            reminder.save()
            messages.success(request, 'Reminder added successfully.')
        else:
            messages.error(request, 'Error saving reminder. Please check the form.')
    return HttpResponseRedirect(reverse('contracts:reminders_popup'))


@conditional_login_required
def reminders_popup_edit(request, reminder_id):
    """
    Handles the Edit Reminder form POST from the popup window.
    AJAX (X-Requested-With) returns JSON; otherwise redirects to default popup view.
    """
    reminder = get_object_or_404(Reminder, id=reminder_id)

    if reminder.reminder_user != request.user and not request.user.is_staff:
        messages.error(request, 'You do not have permission to edit this reminder.')
        if request.method == 'POST' and _request_is_ajax(request):
            return JsonResponse({'success': False}, status=403)
        return HttpResponseRedirect(reverse('contracts:reminders_popup'))

    if request.method == 'POST':
        form = ReminderForm(request.POST, instance=reminder)
        if form.is_valid():
            form.save()
            if _request_is_ajax(request):
                return JsonResponse({'success': True, 'reminder_id': reminder.id})
            messages.success(request, 'Reminder updated.')
        else:
            if _request_is_ajax(request):
                return JsonResponse({'success': False, 'errors': str(form.errors)}, status=400)
            messages.error(request, 'Error updating reminder.')

    return HttpResponseRedirect(reverse('contracts:reminders_popup'))


@conditional_login_required
def toggle_reminder_completion(request, reminder_id):
    reminder = get_object_or_404(Reminder, id=reminder_id)
    
    # Check if the user has permission to update this reminder
    if reminder.reminder_user != request.user and not request.user.is_staff:
        messages.error(request, 'You do not have permission to update this reminder.')
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))
    
    # Toggle the completion status
    reminder.reminder_completed = not reminder.reminder_completed
    
    # Update completion metadata if completing the reminder
    if reminder.reminder_completed:
        reminder.reminder_completed_date = timezone.now()
        reminder.reminder_completed_user = request.user
    else:
        reminder.reminder_completed_date = None
        reminder.reminder_completed_user = None
    
    reminder.save()
    
    messages.success(request, f'Reminder marked as {"completed" if reminder.reminder_completed else "pending"}.')

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'reminder_id': reminder.id,
            'reminder_completed': reminder.reminder_completed,
        })

    return HttpResponseRedirect(request.META.get('HTTP_REFERER', reverse('contracts:reminders_list')))


@conditional_login_required
def mark_reminder_complete(request, reminder_id):
    reminder = get_object_or_404(Reminder, id=reminder_id)
    
    # Check if the user has permission to update this reminder
    if reminder.reminder_user != request.user and not request.user.is_staff:
        messages.error(request, 'You do not have permission to update this reminder.')
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))
    
    # Mark as completed
    reminder.reminder_completed = True
    reminder.reminder_completed_date = timezone.now()
    reminder.reminder_completed_user = request.user
    
    reminder.save()
    
    messages.success(request, 'Reminder marked as completed.')

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'reminder_id': reminder.id,
            'reminder_completed': True,
        })

    return HttpResponseRedirect(request.META.get('HTTP_REFERER', reverse('contracts:reminders_list')))


@conditional_login_required
def edit_reminder(request, reminder_id):
    reminder = get_object_or_404(Reminder, id=reminder_id)
    
    # Check if the user has permission to edit this reminder
    if reminder.reminder_user != request.user and not request.user.is_staff:
        messages.error(request, 'You do not have permission to edit this reminder.')
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))
    
    if request.method == 'POST':
        form = ReminderForm(request.POST, instance=reminder)
        if form.is_valid():
            form.save()
            messages.success(request, 'Reminder updated successfully.')
            
            # Determine the redirect URL
            if reminder.note and reminder.note.content_type.model == 'contract':
                redirect_url = reverse('contracts:contract_management', kwargs={'pk': reminder.note.object_id})
            elif reminder.note and reminder.note.content_type.model == 'clin':
                redirect_url = reverse('contracts:clin_detail', kwargs={'pk': reminder.note.object_id})
            else:
                redirect_url = reverse('contracts:reminders_list')
            
            return HttpResponseRedirect(redirect_url)
    else:
        form = ReminderForm(instance=reminder)
    
    return render(request, 'contracts/reminder_form.html', {
        'form': form,
        'reminder': reminder,
        'is_edit': True
    })


@conditional_login_required
def delete_reminder(request, reminder_id):
    reminder = get_object_or_404(Reminder, id=reminder_id)
    
    # Check if the user has permission to delete this reminder
    if reminder.reminder_user != request.user and not request.user.is_staff:
        messages.error(request, 'You do not have permission to delete this reminder.')
        if _request_is_ajax(request):
            return JsonResponse({'success': False}, status=403)
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))

    reminder.delete()
    messages.success(request, 'Reminder deleted successfully.')

    if _request_is_ajax(request):
        return JsonResponse({'success': True})

    # Redirect back to the referring page
    return HttpResponseRedirect(request.META.get('HTTP_REFERER', reverse('contracts:reminders_list')))


@conditional_login_required
def reminder_counts_api(request):
    """
    Returns the footer pill counts for the current user / active company.
    Used by JS to patch the footer pill badge after AJAX reminder actions
    without a full page reload.
    """
    today = timezone.now().date()
    qs = Reminder.objects.filter(
        reminder_user=request.user,
        reminder_completed=False,
    )
    if getattr(request, 'active_company', None):
        qs = qs.filter(company=request.active_company)

    footer_overdue_count = qs.filter(reminder_date__lt=today).count()
    footer_due_today_count = qs.filter(reminder_date=today).count()

    return JsonResponse({
        'success': True,
        'footer_overdue_count': footer_overdue_count,
        'footer_due_today_count': footer_due_today_count,
        'total': footer_overdue_count + footer_due_today_count,
    })
