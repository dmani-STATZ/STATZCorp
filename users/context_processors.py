from users.user_settings import UserSettings
import time
from .models import SystemMessage, UserCompanyMembership
from contracts.models import Company

def user_preferences(request):
    """
    Add user preferences to the context
    """
    if not request.user.is_authenticated:
        return {'user_preferences': {}, 'cache_version': str(int(time.time()))}

    preferences = UserSettings.get_all_settings(request.user)

    # Add a cache version for CSS files
    cache_version = str(int(time.time()))  # Use current timestamp
    
    # Store in session for consistency across requests
    request.session['cache_version'] = cache_version
    
    return {
        'user_preferences': preferences,
        'cache_version': cache_version
    }

def unread_messages(request):
    """Add unread messages count to the context."""
    if request.user.is_authenticated:
        count = SystemMessage.get_unread_count(request.user)
        return {'unread_messages_count': count}
    return {'unread_messages_count': 0} 

def active_company(request):
    """
    Provide active company and available companies (for selector UI).
    Only authenticated users receive values; others get empty defaults.
    """
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {'active_company': None, 'available_companies': []}

    # Active company set by middleware
    company = getattr(request, 'active_company', None)

    # Available companies for selector
    if request.user.is_superuser:
        companies = list(Company.objects.filter(is_active=True).order_by('name'))
    else:
        companies = [m.company for m in UserCompanyMembership.objects.filter(user=request.user).select_related('company').order_by('company__name')]

    return {
        'active_company': company,
        'available_companies': companies,
    }
