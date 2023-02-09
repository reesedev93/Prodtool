"""appaccounts api URL Configuration

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
from django.urls import path
from .views import (slack_dialog, slack_typeahead, slack_webhook, slack, slack_choose_channel, 
    slack_success, SlackSettingsDeleteItemView, slack_oauth_callback,)

urlpatterns = [
    path('integrations/slack/dialog/', slack_dialog, name='slack-dialog'),
    path('integrations/slack/typeahead/', slack_typeahead, name='slack-typeahead'),
    path('integrations/slack/webhook/', slack_webhook, name='slack-webhook'),
    path('integrations/slack', slack, name='integrations-slack'),
    path('integrations/slack/choose-channel', slack_choose_channel, name='integrations-slack-choose-channel'),
    path('integrations/slack/success', slack_success, name='integrations-slack-success'),
    path('integrations/slack/disable/<int:pk>', SlackSettingsDeleteItemView.as_view(), name='integrations-slack-disable'),
    path('integrations/slack/oauth/callback/', slack_oauth_callback, name='integrations-slack-oauth-callback'),    
]
