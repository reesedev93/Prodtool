from django import template
from guides.models import GuideActivity

register = template.Library()

@register.simple_tag(takes_context=True)
def show_guide(context, guide_name):
    if guide_name not in GuideActivity.GUIDE_KEYS:
        return False

    return not GuideActivity.objects.filter(
        user=context['request'].user, guide=guide_name).exists()
