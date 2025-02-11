from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .forms import UserRegisterForm
from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import User
from .models import Announcement
from .forms import AnnouncementForm
from django.http import JsonResponse


def register(request):
    if request.user.is_authenticated:
        return redirect('home')  # redirect to main page if already logged in
    if request.method == "POST":
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}!')
            return redirect('index')
    else:
        form = UserRegisterForm()
    return render(request, 'users/register.html', {'form': form})


@login_required
def index(request):
    announcements = Announcement.objects.all().order_by('-posted_at')
    return render(request, 'users/index.html', {'announcements': announcements})


def about(request):
    if not request.user.is_authenticated:
        return redirect('landing')  # redirect to main page if already logged in    
    return render(request, 'users/about.html', {'title': 'About'})


def landing_page(request):
    if request.user.is_authenticated:
        return redirect('index')  # redirect to main page if already logged in
    return render(request, 'users/landing.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')  # redirect to main page if already logged in
    return render(request, 'users/login.html')


@login_required
def home(request):  # your authenticated home page
    return render(request, 'users/index.html')


@login_required
def profile(request):
    return render(request, 'users/profile.html')


@receiver(user_logged_out)
def on_user_logged_out(sender, request, **kwargs):
    messages.success(request, 'You have been successfully logged out.')


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
