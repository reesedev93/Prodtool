"""accounts URL Configuration

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
from django.contrib.auth import views as auth_views
from django.urls import path, re_path, include
from . import views

urlpatterns = [
    # copy paste to customize instead of path('', include('django.contrib.auth.urls')),
    path('login/', views.MyLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    path('password_change/', auth_views.PasswordChangeView.as_view(), name='password_change'),
    path('password_change/done/', auth_views.PasswordChangeDoneView.as_view(), name='password_change_done'),

    path('password_reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),

    path('ce-login/', views.ChromeLoginView.as_view(), name='accounts-chrome-extension-login'),
    path('ce-login-successful/', views.chrome_extension_login_successful, name='accounts-chrome-extension-login-successful'),

    path('ce-join/', views.chrome_extension_join, name='accounts-chrome-extension-join'),
    path('ce-join-successful/', views.chrome_extension_join_successful, name='accounts-chrome-extension-join-successful'),
    path('ce-email-not-whitelisted/', views.chrome_extension_email_not_whitelisted, name='accounts-chrome-extension-email-not-whitelisted'),
    re_path(r'^activate/(?P<uid>[0-9]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})/$',
        views.activate_account, name='accounts-activate'),

    path('join/', views.join, name='accounts-join'),
    path('onboarding/tour', views.onboarding_tour, name='accounts-onboarding-tour'),
    path('onboarding/chrome-extension', views.onboarding_chrome_extension, name='accounts-onboarding-chrome-extension'),
    path('onboarding/whitelist', views.onboarding_whitelist, name='accounts-onboarding-whitelist'),
    path('onboarding/customer-data', views.onboarding_customer_data, name='accounts-onboarding-customer-data'),
    path('onboarding/done', views.onboarding_done, name='accounts-onboarding-done'),
    path('onboarding/', views.onboarding_checklist, name='accounts-onboarding-checklist'),

    path('invite-teammates', views.invite_teammates, name='accounts-invite-teammates'),

    path('settings', views.settings_list, name='accounts-settings-list'),
    path('settings/whitelist-domain/', views.WhitelistedDomainSettingsUpdateItemView.as_view(), name='accounts-settings-whitelist-domain'),
    path('settings/submitters-can-create-features/', views.SubmittersCanCreateFeaturesSettingsUpdateItemView.as_view(), name='accounts-settings-submitters-can-create-features'),
    path('settings/feature-request-notifications/<int:pk>', views.FeatureRequestNotificationSettingsUpdateItemView.as_view(), name='accounts-settings-feature-request-notification-settings'),
    path('settings/feedback-triage/', views.FeedbackTriageSettingsUpdateItemView.as_view(), name='accounts-settings-feedback-triage'),
    path('settings/add-credit-card/', views.SubscriptionUpdateItemView.as_view(), name='accounts-settings-add-credit-card'),
    path('no-payment-source-on-file/', views.no_payment_source_on_file, name='accounts-no-payment-source-on-file'),
    path('integration-settings', views.integration_settings_list, name='accounts-integration-settings-list'),

    path('my-settings', views.my_settings_list, name='accounts-my-settings-list'),
    path('my-settings/status-email-settings/<int:pk>', views.StatusEmailSettingsUpdateItemView.as_view(), name='accounts-my-settings-status-email-settings'),
    path('my-settings/status-email-settings/unsubscribe/<uuid:unsubscribe_token>', views.status_email_unsubscribe, name='accounts-my-settings-status-email-unsubscribe'),

    path('users/', views.UserListView.as_view(), name='accounts-user-list'),
    path('users/create/', views.UserCreateItemView.as_view(), name='accounts-user-create-item'),
    path('users/update/<int:pk>', views.UserUpdateItemView.as_view(), name='accounts-user-update-item'),
    path('users/delete/<int:pk>', views.UserDeleteItemView.as_view(), name='accounts-user-delete-item'),

    path('invites/', views.InvitationListView.as_view(), name='accounts-invitation-list'),
    path('invites/create/', views.InviteCreateItemView.as_view(), name='accounts-invitation-create-item'),

    path('<int:id>/sign-up/', views.sign_up, name='accounts-sign-up'),

    path('stripe-webhook/', views.stripe_webhook, name='accounts-stripe-webhook'),
]
