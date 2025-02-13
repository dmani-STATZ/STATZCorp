from django import template
from crispy_forms.utils import TEMPLATE_PACK

register = template.Library()

@register.filter
def tailwind_field(field, css_class=""):
    return field.as_widget(attrs={
        'class': f'w-full p-2 border-2 border-gray-300 rounded-md focus:border-blue-500 focus:ring focus:ring-blue-200 {css_class}'
    })

@register.filter
def tailwind_label(field, css_class=""):
    return field.label_tag(attrs={
        'class': f'block text-sm font-medium text-gray-700 mb-1 {css_class}'
    }) 