from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import (
    Announcement,
    PortalResource,
    PortalSection,
    WorkCalendarEvent,
    WorkCalendarTask,
)


class BaseFormMixin:
    """
    Base form mixin that provides consistent styling for all form widgets.
    This implements the form-styling-rule for the application.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
    
    def _style_fields(self):
        """Apply consistent styling to all form fields based on their widget type."""
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, (forms.TextInput, forms.NumberInput, 
                                forms.EmailInput, forms.URLInput, forms.DateInput, 
                                forms.DateTimeInput, forms.TimeInput, forms.PasswordInput)):
                widget.attrs['class'] = 'form-input'
            elif isinstance(widget, forms.Select):
                widget.attrs['class'] = 'form-select'
            elif isinstance(widget, forms.Textarea):
                widget.attrs['class'] = 'form-input'
                if 'rows' not in widget.attrs:
                    widget.attrs['rows'] = 3
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = 'form-checkbox'
            
            # Add placeholder if not present
            if not widget.attrs.get('placeholder') and field.label:
                widget.attrs['placeholder'] = f'Enter {field.label}'


class BaseModelForm(BaseFormMixin, forms.ModelForm):
    """Base ModelForm that implements the form-styling-rule."""
    pass


class BaseForm(BaseFormMixin, forms.Form):
    """Base Form that implements the form-styling-rule."""
    pass

class UserRegisterForm(BaseFormMixin, UserCreationForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

class AnnouncementForm(BaseModelForm):
    class Meta:
        model = Announcement
        fields = ['title', 'content']


class PortalSectionForm(BaseModelForm):
    class Meta:
        model = PortalSection
        fields = ['title', 'description']


class PortalResourceForm(BaseModelForm):
    class Meta:
        model = PortalResource
        fields = [
            'section',
            'title',
            'description',
            'resource_type',
            'file',
            'external_url',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class WorkCalendarTaskForm(BaseModelForm):
    class Meta:
        model = WorkCalendarTask
        fields = [
            'title',
            'description',
            'due_date',
            'importance',
            'energy_required',
            'estimated_minutes',
            'status',
            'source_app',
            'metadata',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'metadata': forms.Textarea(attrs={'rows': 3}),
        }


class WorkCalendarEventForm(BaseModelForm):
    class Meta:
        model = WorkCalendarEvent
        fields = [
            'title',
            'description',
            'start_at',
            'end_at',
            'location',
            'priority',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'start_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'end_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class AdminLoginForm(BaseFormMixin, forms.Form):
    """Admin login form with consistent styling"""
    username = forms.CharField(max_length=150, label='Username')
    password = forms.CharField(widget=forms.PasswordInput, label='Password')


class PasswordChangeForm(BaseFormMixin, forms.Form):
    """Password change form with consistent styling - no current password required"""
    new_password1 = forms.CharField(widget=forms.PasswordInput, label='New Password')
    new_password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm New Password')

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        new_password1 = cleaned_data.get('new_password1')
        new_password2 = cleaned_data.get('new_password2')

        if new_password1 and new_password2:
            if new_password1 != new_password2:
                raise forms.ValidationError('New passwords do not match.')
            if len(new_password1) < 8:
                raise forms.ValidationError('New password must be at least 8 characters long.')

        return cleaned_data


class PasswordSetForm(BaseFormMixin, forms.Form):
    """Password set form for users without passwords"""
    new_password1 = forms.CharField(widget=forms.PasswordInput, label='New Password')
    new_password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm New Password')

    def clean(self):
        cleaned_data = super().clean()
        new_password1 = cleaned_data.get('new_password1')
        new_password2 = cleaned_data.get('new_password2')

        if new_password1 and new_password2:
            if new_password1 != new_password2:
                raise forms.ValidationError('Passwords do not match.')
            if len(new_password1) < 8:
                raise forms.ValidationError('Password must be at least 8 characters long.')

        return cleaned_data


class EmailLookupForm(BaseFormMixin, forms.Form):
    """Email lookup form for OAuth users to set passwords"""
    email = forms.EmailField(label='Email Address', help_text='Enter the email address associated with your account')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        try:
            user = User.objects.get(email=email)
            # Allow both OAuth users (no password) and users who want to change their password
            return email
        except User.DoesNotExist:
            raise forms.ValidationError('No account found with this email address. Please contact your administrator.')


class OAuthPasswordSetForm(BaseFormMixin, forms.Form):
    """Password set form specifically for OAuth users"""
    new_password1 = forms.CharField(widget=forms.PasswordInput, label='New Password')
    new_password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm New Password')

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        new_password1 = cleaned_data.get('new_password1')
        new_password2 = cleaned_data.get('new_password2')

        if new_password1 and new_password2:
            if new_password1 != new_password2:
                raise forms.ValidationError('Passwords do not match.')
            if len(new_password1) < 8:
                raise forms.ValidationError('Password must be at least 8 characters long.')

        return cleaned_data
