from django import forms
from .models import Visitor, Staged
from django.utils import timezone
from django.db.models import DateTimeField
from django.db.models.functions import TruncMonth

class VisitorHistoryField(forms.ChoiceField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.populate_choices()

    def populate_choices(self):
        # Get unique visitor names from both Visitor and Staged models
        staged = Staged.objects.values('id', 'visitor_name', 'visitor_company').distinct()
        visitors = Visitor.objects.values('visitor_name', 'visitor_company').distinct()

        # Add Staged Visitors section only if there are staged visitors
        choices = []
        if staged.exists():
            choices.append(('', '-- Staged Visitors --'))
            choices.extend([
                (str(item['id']), f"{item['visitor_name']} - {item['visitor_company']}")
                for item in sorted(staged, key=lambda x: x['visitor_name'])
            ])

        # Add separator and previous visitors section if there are previous visitors
        if visitors.exists():
            choices.append(('', '-- Select Previous Visitor --'))
            choices.extend([
                (name, f"{name} - {company}")
                for name, company in sorted(set((v['visitor_name'], v['visitor_company']) for v in visitors))
            ])

        self.choices = choices



class VisitorCheckInForm(forms.ModelForm):
    visitor_history = VisitorHistoryField(required=False)
    
    class Meta:
        model = Visitor
        fields = ['visitor_name', 'visitor_company', 'reason_for_visit', 'is_us_citizen']
        widgets = {
            'visitor_name': forms.TextInput(attrs={
                'class': 'w-full p-2 border-2 border-gray-300 rounded-md focus:border-blue-500 focus:ring focus:ring-blue-200'
            }),
            'visitor_company': forms.TextInput(attrs={
                'class': 'w-full p-2 border-2 border-gray-300 rounded-md focus:border-blue-500 focus:ring focus:ring-blue-200'
            }),
            'reason_for_visit': forms.TextInput(attrs={
                'class': 'w-full p-2 border-2 border-gray-300 rounded-md focus:border-blue-500 focus:ring focus:ring-blue-200'
            }),
            'is_us_citizen': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
            }),
        }
        labels = {
            'is_us_citizen': 'US Citizen'
        }

class MonthYearForm(forms.Form):
    month_year = forms.ChoiceField(
        choices=[],
        label=''
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get unique months from visitor log
        dates = (Visitor.objects
                .annotate(month=TruncMonth('date_of_visit'))
                .values('month')
                .distinct()
                .order_by('-month'))
        
        self.fields['month_year'].choices = [('', 'Select Month')] + [
            (d['month'].strftime('%Y-%m'), d['month'].strftime('%B %Y'))
            for d in dates
        ] 

