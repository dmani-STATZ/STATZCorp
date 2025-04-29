from django import template
register = template.Library()

@register.simple_tag(takes_context=True)
def is_cert_untrusted(context):
    request = context['request']
    return request.is_secure() and not request.META.get('HTTP_X_SSL_CERT_VERIFY') == 'SUCCESS'
