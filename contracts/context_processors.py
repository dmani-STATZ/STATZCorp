from django.utils import timezone
from .models import Reminder
from django.db.models import Q
from django.db import ProgrammingError

def reminders_processor(request):
    """
    Context processor that adds reminders for the current user to all templates.
    """
    context = {}
    
    # Only add reminders if the user is authenticated
    if request.user.is_authenticated:
        try:
            # Get reminders for the current user, explicitly selecting only the fields we need
            # to avoid the note_id column that might be missing
            reminders = Reminder.objects.filter(
                reminder_user=request.user
            ).only(
                'id', 'reminder_title', 'reminder_text', 'reminder_date', 
                'reminder_completed', 'reminder_user'
            ).order_by('reminder_completed', 'reminder_date')[:10]
            
            # Add current time for comparison in templates
            context['now'] = timezone.now()
            context['reminders'] = reminders
        except ProgrammingError:
            # Handle database schema mismatch gracefully
            context['reminders'] = []
            context['now'] = timezone.now()
    
    return context 