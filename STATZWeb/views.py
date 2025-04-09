from django.shortcuts import render, redirect
from users.models import Announcement
from django.contrib.auth.decorators import permission_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.conf import settings
from datetime import datetime
from django.utils.timezone import make_aware
from STATZWeb.decorators import conditional_login_required

def index(request):
    announcements = Announcement.objects.all().order_by('-posted_at')
    return render(request, 'index.html', {'announcements': announcements})

@conditional_login_required
def about(request):
    return render(request, 'about.html', {'title': 'About'})
 

def landing_page(request):
    return render(request, 'landing.html')

@permission_required('users.add_announcement', raise_exception=True)
def add_announcement(request):
    if request.method == 'POST':
        content = request.POST.get('content')
        if content:
            announcement = Announcement.objects.create(
                content=content,
                posted_by=request.user
            )
            return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)


@permission_required('users.delete_announcement', raise_exception=True)
def delete_announcement(request, announcement_id):
    announcement = get_object_or_404(Announcement, id=announcement_id)
    if request.method == 'POST':
        announcement.delete()
        return redirect('index')
    return render(request, 'users/delete_announcement.html', {'announcement': announcement})