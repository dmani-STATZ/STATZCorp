from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Look up ``key`` in ``dictionary`` from a template.

    Django templates do not support dict access with a variable key
    using standard ``{{ d.key }}`` syntax when ``key`` itself is a
    template variable. This filter enables ``{{ d|get_item:key }}``.
    """
    if dictionary is None:
        return None
    return dictionary.get(key)
