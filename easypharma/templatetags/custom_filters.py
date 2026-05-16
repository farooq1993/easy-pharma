from django import template

register = template.Library()

@register.filter(name='getattr')
def get_model_attr(obj, attr):
    """
    Safely get an attribute from an object.
    Renamed internally to avoid shadowing built-in getattr.
    """
    return getattr(obj, attr, '')

# ── Add this to your existing easypharma/templatetags/custom_filters.py ──
# (Do NOT create a new file — just paste these lines at the bottom)

from django import template

register = template.Library()   # remove this line if register already exists at top of custom_filters.py

@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """
    Preserves all current GET params and overrides the ones you pass.
    Usage:  href="?{% url_replace page=3 %}"
    Requires 'django.template.context_processors.request' in TEMPLATES CONTEXT_PROCESSORS.
    """
    request = context.get('request')
    if not request:
        return ''
    params = request.GET.copy()
    for key, value in kwargs.items():
        params[key] = value
    return params.urlencode()