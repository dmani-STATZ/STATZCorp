from users.user_settings import UserSettings

def user_preferences(request):
    if request.user.is_authenticated:
        preferences = UserSettings.get_multiple_settings(request.user, ['theme'])
    else:
        preferences = {'theme': 'light'}
    return {'user_preferences': preferences} 