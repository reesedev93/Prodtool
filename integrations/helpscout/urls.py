"""intercom URL Configuration

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
from django.urls import path, re_path
from . import views

urlpatterns = [
    path('integrations/helpscout/receive-webhook/<secret>', views.receive_webhook, name='integrations-helpscout-receive-webhook'),
    path('integrations/helpscout/oauth/callback/', views.oauth_callback, name='integrations-helpscout-oauth-callback'),
    path('integrations/helpscout/settings/', views.HelpScoutSettingsUpdateItemView.as_view(), name='integrations-helpscout-update-settings'),
    path('integrations/helpscout/generate-random-user/', views.generate_random_helpscout_user, name='integrations-helpscout-generate-random-user'),
]
