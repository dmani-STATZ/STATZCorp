from django import forms
from .models import Visitor, Staged
from django.utils import timezone
from django.db.models import DateTimeField
from django.db.models.functions import TruncMonth

class VisitorHistoryField(forms.ChoiceField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get unique visitor names from both Visitor and Staged models
        visitors = Visitor.objects.values('visitor_name').distinct()
        staged = Staged.objects.values('visitor_name').distinct()
        
        # Combine and deduplicate visitor names
        all_names = set()
        for v in visitors:
            all_names.add(v['visitor_name'])
        for s in staged:
            all_names.add(s['visitor_name'])
        
        # Create choices list
        choices = [('', '-- Select Previous Visitor --')]
        choices.extend([(name, name) for name in sorted(all_names)])
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
    month_year = forms.ChoiceField(
        choices=[],
        label='Select Month'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get unique months from visitor log
        dates = (Visitor.objects
                .annotate(month=TruncMonth('date_of_visit'))
                .values('month')
                .distinct()
                .order_by('-month'))
        
        self.fields['month_year'].choices = [
            (d['month'].strftime('%Y-%m'), d['month'].strftime('%B %Y'))
            for d in dates
        ] 

