from django import template

register = template.Library()

@register.filter(name='getattr')
def get_model_attr(obj, attr):
    """
    Safely get an attribute from an object.
    Renamed internally to avoid shadowing built-in getattr.
    """
    return getattr(obj, attr, '')
