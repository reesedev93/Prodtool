from collections import OrderedDict
from urllib.parse import urlencode
from django import template

register = template.Library()

@register.inclusion_tag('includes/table_headers.html', takes_context=True)
def table_header(context, headers):
    """
    headers: is list of headers for the list
    """
    return {
        'headers': headers,
    }
