"""feedback URL Configuration

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

from . import views
from .admin_views import UploadFeedbackView

urlpatterns = [
    path(
        "inbox/<int:pk>",
        views.FeedbackInboxItemView.as_view(),
        name="feedback-inbox-item",
    ),
    path(
        "inbox/<state>",
        views.FeedbackInboxListView.as_view(),
        name="feedback-inbox-list",
    ),
    path(
        "inbox/create/",
        views.FeedbackInboxCreateItemView.as_view(),
        name="feedback-inbox-create-item",
    ),
    path(
        "inbox/update/<int:pk>",
        views.FeedbackInboxUpdateItemView.as_view(),
        name="feedback_inbox_update_item",
    ),
    path("feedback", views.FeedbackListView.as_view(), name="feedback-list"),
    path("feedback/<int:pk>", views.FeedbackItemView.as_view(), name="feedback-item"),
    path(
        "feedback/create/",
        views.FeedbackCreateItemView.as_view(),
        name="feedback-create-item",
    ),
    path(
        "feedback/update/<int:pk>",
        views.FeedbackUpdateItemView.as_view(),
        name="feedback-update-item",
    ),
    path(
        "feedback/delete/<int:pk>",
        views.FeedbackDeleteItemView.as_view(),
        name="feedback-delete-item",
    ),
    path(
        "feature-request-autocomplete/",
        views.FeatureRequestAutocomplete.as_view(create_field="title"),
        name="feature-request-autocomplete",
    ),
    path(
        "feature-request-autocomplete-no-create/",
        views.FeatureRequestAutocompleteNoCreate.as_view(create_field="title"),
        name="feature-request-autocomplete-no-create",
    ),
    path(
        "feature-requests",
        views.FeatureRequestListView.as_view(),
        name="feature-request-list",
    ),
    path(
        "feature-request/update/<int:pk>",
        views.FeatureRequestUpdateItemView.as_view(),
        name="feature-request-update-item",
    ),
    path(
        "feature-request/create/",
        views.FeatureRequestCreateItemView.as_view(),
        name="feature-request-create-item",
    ),
    path(
        "feature-request-ajax-create/",
        views.feature_request_ajax_create,
        name="feature-request-ajax-create",
    ),
    path(
        "feature-request/delete/<int:pk>",
        views.FeatureRequestDeleteItemView.as_view(),
        name="feature-request-delete-item",
    ),
    path(
        "feature-request/feedback/<int:pk>",
        views.FeatureRequestFeedbackDetailsView.as_view(),
        name="feature-request-feedback-details",
    ),
    path(
        "feature-request/close-the-loop/",
        views.CloseLoopView.as_view(),
        name="feature-request-close-the-loop",
    ),
    path(
        "feature-request/send-test-email/",
        views.fr_send_test_email,
        name="feature-request-send-test-email",
    ),
    path(
        "feature-request/merge/",
        views.FeatureRequestMergeItemView.as_view(),
        name="feature-request-merge-item",
    ),
    path("themes", views.ThemeListView.as_view(), name="theme-list"),
    path(
        "theme/create/", views.ThemeCreateItemView.as_view(), name="theme-create-item"
    ),
    path(
        "theme-autocomplete/",
        views.ThemeAutocomplete.as_view(create_field="title"),
        name="theme-autocomplete",
    ),
    path(
        "theme/update/<int:pk>",
        views.ThemeUpdateItemView.as_view(),
        name="theme-update-item",
    ),
    path(
        "theme/delete/<int:pk>",
        views.ThemeDeleteItemView.as_view(),
        name="theme-delete-item",
    ),
    path(
        "settings/import/disconnect/<int:pk>",
        views.CustomerFeedbackImporterSettingsDeleteItemView.as_view(),
        name="customer-feedback-importer-settings-delete-item",
    ),
    path(
        "settings/feedback-from/edit/<int:pk>",
        views.FeedbackFromRuleEditItemView.as_view(),
        name="feedback-from-rule-update-item",
    ),
    path(
        "settings/feedback-template/edit/<int:pk>",
        views.FeedbackTemplateEditItemView.as_view(),
        name="feedback-template-update-item",
    ),
    path(
        "admin/upload-feedback",
        UploadFeedbackView.as_view(),
        name="feedback-admin-upload-feedback",
    ),
]
