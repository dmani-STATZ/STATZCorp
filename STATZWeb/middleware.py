from django.shortcuts import redirect
from django.conf import settings
from django.urls import reverse
from django.contrib.auth.decorators import login_required

class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # URLs that should always be accessible
        self.public_urls = [
            reverse('users:login'),
            reverse('users:register'),
            reverse('users:logout'),
            reverse('landing'),
            '/admin/',  # Admin pages
            '/static/',  # Static files
            '/media/',  # Media files
        ]

    def __call__(self, request):
        if settings.REQUIRE_LOGIN:
            if not request.user.is_authenticated:
                path = request.path_info
                if not any(url in path for url in self.public_urls):
                    return redirect(settings.LOGIN_URL)
        
        response = self.get_response(request)
        return response 