from django.conf import settings
import hashlib
import urllib
from django import template
from django.utils.safestring import mark_safe
 
register = template.Library()
 
# return only the URL of the gravatar
# TEMPLATE USE:  {{ user|gravatar_url:150 }}
@register.filter
def gravatar_url(user, size=50):
    default = settings.HOST + "/static/images/avatar.png"
    email = ''
    if user: # and (user.email.find("@example.com") > -1):
        if user.name == "Olenna Tyrell":
            default = settings.HOST + "/static/images/dummy/olenna.png"
        elif user.name == "Helen Parr":
            default = settings.HOST + "/static/images/dummy/helen.png"
        elif user.name == "Kaladin Stormblessed":
            default = settings.HOST + "/static/images/dummy/kaladin3.png"
        elif user.name == "Cosmo Kramer":
            default = settings.HOST + "/static/images/dummy/cosmo.png"
        elif user.name == "Cho Chang":
            default = settings.HOST + "/static/images/dummy/cho2.png"
        elif user.name == "Oberyn Martell":
            default = settings.HOST + "/static/images/dummy/oberyn2.png"
        elif user.name == "Dash Parr":
            default = settings.HOST + "/static/images/dummy/dash.png"

    return "https://www.gravatar.com/avatar/%s?%s" % (hashlib.md5(email.encode('utf-8').lower()).hexdigest(), urllib.parse.urlencode({'d':default, 's':str(size)}))
 
# return an image tag with the gravatar
# TEMPLATE USE:  {{ email|gravatar:150 }}
@register.filter
def gravatar(email, size=50):
    url = gravatar_url(email, size)
    return mark_safe('<img src="%s" height="%d" width="%d">' % (url, size, size))
