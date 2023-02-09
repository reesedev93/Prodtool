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
from .views import (receive_intercom_webhook, intercom_oauth_callback, generate_random_intercom_user,
    IntercomSettingsUpdateItemView)

urlpatterns = [
    path('receive-intercom-webhook/', receive_intercom_webhook, name='intercom-receive-intercom-webhook'),
    path('accounts/oauth/intercom/callback/', intercom_oauth_callback, name='intercom-oauth-intercom-callback'),
    path('integrations/intercom/settings/', IntercomSettingsUpdateItemView.as_view(), name='integrations-intercom-update-settings'),
    path('integrations/intercom/generate-random-user/', generate_random_intercom_user, name='integrations-intercom-generate-random-user'),
]
