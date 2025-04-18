from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse, HttpResponseRedirect
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta

from STATZWeb.decorators import conditional_login_required
from ..models import Reminder, Note
from ..forms import ReminderForm


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
        
        # Filter by completion status if specified
        status_filter = self.request.GET.get('status')
        if status_filter == 'completed':
            queryset = queryset.filter(reminder_completed=True)
        elif status_filter == 'pending':
            queryset = queryset.filter(Q(reminder_completed=False) | Q(reminder_completed__isnull=True))
        
        # Filter by due date if specified
        due_filter = self.request.GET.get('due')
        today = timezone.now().date()
        seven_days_ago = today - timedelta(days=7)
        
        if due_filter == 'overdue':
            # Overdue: reminder_date <= today-7days
            queryset = queryset.filter(
                reminder_date__date__lte=seven_days_ago, 
                reminder_completed=False
            )
        elif due_filter == 'due':
            # Due: reminder_date <= today AND reminder_date > today-7days
            queryset = queryset.filter(
                reminder_date__date__lte=today,
                reminder_date__date__gt=seven_days_ago,
                reminder_completed=False
            )
        elif due_filter == 'upcoming':
            # Future/Pending: reminder_date > today
            queryset = queryset.filter(
                reminder_date__date__gt=today,
                reminder_completed=False
            )
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.now().date()
        seven_days_ago = today - timedelta(days=7)
        
        # Add filter parameters to context
        context['status_filter'] = self.request.GET.get('status', '')
        context['due_filter'] = self.request.GET.get('due', '')
        
        # Add counts for different reminder categories
        all_reminders = Reminder.objects.filter(reminder_user=user)
        
        context['total_count'] = all_reminders.count()
        context['completed_count'] = all_reminders.filter(reminder_completed=True).count()
        
        # Get non-completed reminders
        active_reminders = all_reminders.filter(
            Q(reminder_completed=False) | Q(reminder_completed__isnull=True)
        )
        context['pending_count'] = active_reminders.count()
        
        # Overdue: reminder_date <= today-7days
        context['overdue_count'] = active_reminders.filter(
            reminder_date__date__lte=seven_days_ago
        ).count()
        
        # Due: reminder_date <= today AND reminder_date > today-7days
        context['due_count'] = active_reminders.filter(
            reminder_date__date__lte=today,
            reminder_date__date__gt=seven_days_ago
        ).count()
        
        # Future/Pending: reminder_date > today
        context['upcoming_count'] = active_reminders.filter(
            reminder_date__date__gt=today
        ).count()
        
        # Add seven_days_ago to context for template use
        context['seven_days_ago'] = seven_days_ago
        context['today'] = today
        
        # Process reminders to add is_overdue flag
        for reminder in context['reminders_page']:
            reminder.is_overdue = reminder.reminder_date.date() <= seven_days_ago
        
        return context


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
    
    # Redirect back to the referring page
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
    
    # Redirect back to the referring page
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
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))
    
    # Delete the reminder
    reminder.delete()
    
    messages.success(request, 'Reminder deleted successfully.')
    
    # Redirect back to the referring page
    return HttpResponseRedirect(request.META.get('HTTP_REFERER', reverse('contracts:reminders_list'))) 