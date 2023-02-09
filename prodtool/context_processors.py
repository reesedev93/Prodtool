from django.conf import settings

def exposed_settings(request):
    # return the value you want as a dictionnary. you may add multiple values in there.
    return {
        'PRODUCTION': settings.PRODUCTION,
        'INTERCOM_APP_ID': settings.INTERCOM_APP_ID,
    }

def getvars(request):
    """
    Builds a GET variables string to be uses in template links like pagination
    when persistence of the GET vars is needed.
    """
    variables = request.GET.copy()

    if 'page' in variables:
        del variables['page']

    if variables:
        qstring = {'getvars': '&{0}'.format(variables.urlencode())}
    else:
        qstring = ""
    return qstring
