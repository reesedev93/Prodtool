"""prodtool URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic.base import RedirectView

urlpatterns = [
    path('app/cron/', include('cron.urls')),
    path('app/accounts/', include('accounts.urls')),
    path('app/appaccounts/', include('appaccounts.urls')),
    path('app/dummy-data/', include('dummydata.urls')),
    path('app/api/', include('api.urls')),
    path('app/', include('feedback.urls')),
    path('app/', include('integrations.slack.urls')),
    path('app/', include('integrations.intercom.urls')),
    path('app/', include('integrations.helpscout.urls')),
    path('app/', include('integrations.segment.urls')),
    path('app/', include('integrations.email.urls')),
    path('app/internal-analytics/', include('internal_analytics.urls')),
    path('app/guides/', include('guides.urls')),
    path('admin/', admin.site.urls),
    path('app/api/api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('ce', RedirectView.as_view(url='https://chrome.google.com/webstore/detail/savio/iihflnhbcjoeneakjblkjhmmfiggjakf'), name="download-chrome-extension"),
    path('', include('marketing.urls')), # CAREFUL: headless cms will gobble up anything doesn't start with /app or /admin
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls)),

        # For django versions before 2.0:
        # url(r'^__debug__/', include(debug_toolbar.urls)),

    ] + urlpatterns