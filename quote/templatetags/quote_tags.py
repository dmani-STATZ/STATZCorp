"""Quotes template tags. The Test Mode banner reads the settings once and never raises."""
import logging

from django import template

from quote.services.outbound import test_mode_state

register = template.Library()
logger = logging.getLogger(__name__)


@register.inclusion_tag('quote/includes/test_mode_banner.html', takes_context=True)
def quote_test_mode_banner(context):
    """Nothing when Test Mode is off. On any failure: nothing, and the send path is unaffected."""
    try:
        state = test_mode_state()
        if not state['on']:
            return {'show': False}
        user = context['request'].user
        return {
            'show': True,
            'recipient': state['recipient'],
            'is_superuser': bool(getattr(user, 'is_superuser', False)),
        }
    except Exception:
        logger.exception('quote test mode banner failed')
        return {'show': False}
