from users.user_settings import UserSettings
import time
from .models import SystemMessage

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