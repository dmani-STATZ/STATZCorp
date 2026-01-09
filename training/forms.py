from django import forms
from django.contrib.auth.models import User
from .models import Course, Account, Matrix, ArcticWolfCourse, UserAccount

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
            if isinstance(widget, (
                forms.TextInput,
                forms.NumberInput,
                forms.DateInput,
                forms.DateTimeInput,
                forms.EmailInput,
                forms.URLInput,
                forms.PasswordInput,
                forms.Select,
                forms.NullBooleanSelect,
                forms.SelectMultiple,
                forms.RadioSelect,
                forms.CheckboxInput,
                forms.FileInput,
                forms.Textarea,
                forms.CharField.widget, # Handle custom widgets
                forms.IntegerField.widget,
                forms.FloatField.widget,
                forms.DecimalField.widget,
                forms.BooleanField.widget,
                forms.DateField.widget,
                forms.DateTimeField.widget,
                forms.TimeField.widget,
                forms.DurationField.widget,
                forms.ChoiceField.widget,
                forms.MultipleChoiceField.widget,
                forms.ModelChoiceField.widget,
                forms.ModelMultipleChoiceField.widget,
            )):
                if 'class' in widget.attrs:
                    widget.attrs['class'] += ' form-input'
                else:
                    widget.attrs['class'] = 'form-input'
            if isinstance(widget, forms.Select):
                widget.attrs['class'] = 'form-select'
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = 'form-checkbox'
            elif isinstance(widget, forms.Textarea):
                widget.attrs['class'] = 'form-input' # Textarea gets form-input styling
            elif isinstance(widget, forms.SelectMultiple):
                widget.attrs['class'] = 'form-select' # Treat multiple selects as selects

            field.widget.attrs['placeholder'] = field.label.capitalize() # Apply automatic placeholders

class BaseModelForm(BaseFormMixin, forms.ModelForm):
    pass

class BaseForm(BaseFormMixin, forms.Form):
    pass

class CourseForm(BaseModelForm):
    class Meta:
        model = Course
        fields = ['name', 'link', 'description', 'upload']

class AccountForm(BaseModelForm):
    class Meta:
        model = Account
        fields = ['type', 'description']

class MatrixForm(BaseModelForm):
    class Meta:
        model = Matrix
        fields = ['course', 'account', 'frequency']
        
class MatrixManagementForm(BaseForm):
    account = forms.ModelChoiceField(
        queryset=Account.objects.all().order_by('type'),
        label="Account",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].empty_label = "Select Account"

class ArcticWolfCourseForm(BaseModelForm):
    class Meta:
        model = ArcticWolfCourse
        fields = ['name', 'description']

class CmmcDocumentUploadForm(BaseForm):
    """
    Form for administrators to upload CMMC training documents for users.
    Validates that the selected user/course combination is valid according to the CMMC matrix.
    """
    user = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('username'),
        label="User",
        empty_label="Select a user"
    )
    course = forms.ModelChoiceField(
        queryset=Course.objects.all().order_by('name'),
        label="Course",
        empty_label="Select a course"
    )
    file = forms.FileField(
        label="Document",
        help_text="Upload supporting document for this training completion",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Apply specific styling for file input
        self.fields['file'].widget.attrs['class'] = 'form-input'
        self.fields['file'].widget.attrs['accept'] = '.pdf,.doc,.docx,.jpg,.jpeg,.png'

    def clean(self):
        cleaned_data = super().clean()
        user = cleaned_data.get('user')
        course = cleaned_data.get('course')

        if user and course:
            # Check if the user has any account types that require this course
            user_accounts = UserAccount.objects.filter(user=user).values_list('account_id', flat=True)
            valid_matrix = Matrix.objects.filter(
                account__in=user_accounts,
                course=course
            ).exists()

            if not valid_matrix:
                raise forms.ValidationError(
                    f"The selected user '{user.username}' is not required to complete the course '{course.name}' "
                    "according to the CMMC matrix. Please select a valid user/course combination."
                )

        return cleaned_data
