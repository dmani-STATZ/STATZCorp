from django import forms
from .models import Visitor
from django.utils import timezone

class VisitorHistoryField(forms.ChoiceField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get unique visitor names
        visitors = Visitor.objects.values('visitor_name').distinct().order_by('visitor_name')
        choices = [('', '-- Select Previous Visitor --')]
        choices.extend([(v['visitor_name'], v['visitor_name']) for v in visitors])
        self.choices = choices

class VisitorCheckInForm(forms.ModelForm):
    visitor_history = VisitorHistoryField(required=False)
    
    class Meta:
        model = Visitor
        fields = ['visitor_name', 'visitor_company', 'reason_for_visit', 'is_us_citizen']
        widgets = {
            'visitor_name': forms.TextInput(attrs={'class': 'form-control'}),
            'visitor_company': forms.TextInput(attrs={'class': 'form-control'}),
            'reason_for_visit': forms.TextInput(attrs={'class': 'form-control'}),
            'is_us_citizen': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'is_us_citizen': 'US Citizen'
        }

class MonthYearForm(forms.Form):
    MONTH_CHOICES = [
        (1, 'January'), (2, 'February'), (3, 'March'),
        (4, 'April'), (5, 'May'), (6, 'June'),
        (7, 'July'), (8, 'August'), (9, 'September'),
        (10, 'October'), (11, 'November'), (12, 'December'),
    ]
    month = forms.ChoiceField(choices=MONTH_CHOICES)
    year = forms.IntegerField(min_value=2000, max_value=2100) 