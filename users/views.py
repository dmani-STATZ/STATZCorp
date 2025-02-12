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



