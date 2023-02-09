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
from django.urls import include, path, re_path
from rest_framework import routers
from rest_framework.authtoken.views import obtain_auth_token

from . import views

router = routers.DefaultRouter()
router.register(r"users", views.AppUserViewSet, base_name="user")
router.register(r"feedback", views.FeedbackViewSet, base_name="feedback")
router.register(
    r"detailed-feedback", views.DetailedFeedbackViewSet, base_name="detailedfeedback"
)
router.register(
    r"featurerequest", views.FeatureRequestViewSet, base_name="featurerequest"
)
# router.register(r'chrome-extension-create', chrome_extension_create_feedback, base_name='feedback')
urlpatterns = [
    path("auth/token-auth/", obtain_auth_token),
    path(
        "auth/get-user-from-token/",
        views.get_user_from_auth_token,
        name="chrome-get-user-from-token",
    ),
    path("auth/me/", views.check_user_auth, name="api-check-user-auth"),
    re_path(r"^", include(router.urls)),
    path(
        "chrome-extension/create-feedback/",
        views.chrome_extension_create_feedback,
        name="chrome-extension-create-feedback",
    ),
    path("create-feedback/", views.create_feedback, name="api-create-feedback"),
]
