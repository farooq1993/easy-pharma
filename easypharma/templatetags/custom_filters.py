from django import template

register = template.Library()


@register.filter(name='getattr')
def get_model_attr(obj, attr):
    """Safely get an attribute from an object; returns empty string on error."""
    try:
        return getattr(obj, attr, '')
    except Exception:
        return ''


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """Preserves current GET params and overrides provided ones.

    Usage: href="?{% url_replace page=3 %}"
    Requires 'django.template.context_processors.request' in TEMPLATES context processors.
    """
    request = context.get('request')
    if not request:
        return ''
    params = request.GET.copy()
    for key, value in kwargs.items():
        params[key] = value
    return params.urlencode()

@register.filter
def tag_icon(tag):
    return 'check-circle' if tag == 'success' else 'exclamation-triangle'


@register.filter
def get_item(dictionary, key):
    """Allow dict[key] lookup in templates: {{ my_dict|get_item:some_var }}"""
    if dictionary is None:
        return None
    return dictionary.get(key)
