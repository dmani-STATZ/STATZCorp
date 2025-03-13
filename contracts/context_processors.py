from django.utils import timezone
from .models import Reminder
from django.db.models import Q
from django.db import ProgrammingError
from datetime import timedelta

def reminders_processor(request):
    """
    Context processor that adds reminders for the current user to all templates.
    """
    context = {}
    
    # Only add reminders if the user is authenticated
    if request.user.is_authenticated:
        try:
            now = timezone.now()
            today = now.date()
            seven_days_ago = today - timedelta(days=7)
            
            # Get all non-completed reminders for this user
            all_reminders = Reminder.objects.filter(
                reminder_user=request.user,
                reminder_completed=False
            )
            
            # Categorize reminders based on exact requirements:
            # - Pending: reminder_date > today (not visible)
            # - Due: reminder_date <= today AND reminder_date > today-7days (visible)
            # - Overdue: reminder_date <= today-7days (visible)
            
            # Pending reminders - future dates (not shown in sidebar)
            pending_count = all_reminders.filter(
                reminder_date__date__gt=today
            ).count()
            
            # Due reminders - today and within past 7 days (visible in sidebar)
            due_count = all_reminders.filter(
                reminder_date__date__lte=today,
                reminder_date__date__gt=seven_days_ago
            ).count()
            
            # Overdue reminders - more than 7 days old (visible in sidebar)
            overdue_count = all_reminders.filter(
                reminder_date__date__lte=seven_days_ago
            ).count()
            
            # For sidebar display, we want to include all due and overdue reminders
            # Order by date with overdue ones first
            sidebar_reminders = Reminder.objects.filter(
                reminder_user=request.user,
                reminder_completed=False,
                reminder_date__date__lte=today
            ).order_by('reminder_date__date')[:30]  # Increased limit to show more reminders
            
            # Add is_overdue flag to each reminder object
            for reminder in sidebar_reminders:
                reminder.is_overdue = reminder.reminder_date.date() <= seven_days_ago
                # Also rename fields to match template
                reminder.title = reminder.reminder_title
                reminder.description = reminder.reminder_text
                reminder.completed = reminder.reminder_completed
            
            # Get total count of all non-completed reminders
            total_active_reminders = all_reminders.count()
            
            # Add to context
            context['now'] = now
            context['today'] = today
            context['seven_days_ago'] = seven_days_ago
            context['reminders'] = sidebar_reminders
            context['total_reminders_count'] = total_active_reminders
            context['pending_count'] = pending_count
            context['due_count'] = due_count
            context['overdue_count'] = overdue_count
            
        except ProgrammingError:
            # Handle database schema mismatch gracefully
            context['reminders'] = []
            context['now'] = timezone.now()
            context['today'] = timezone.now().date()
            context['seven_days_ago'] = timezone.now().date() - timedelta(days=7)
            context['total_reminders_count'] = 0
            context['pending_count'] = 0
            context['due_count'] = 0
            context['overdue_count'] = 0
    
    return context 