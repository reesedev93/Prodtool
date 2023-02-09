"""appaccounts URL Configuration

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

urlpatterns = [
    path(
        "app-company-autocomplete-no-create/",
        views.AppCompanyAutocompleteNoCreate.as_view(),
        name="app-company-autocomplete-no-create",
    ),
    path(
        "app-company-autocomplete/",
        views.AppCompanyAutocomplete.as_view(create_field="name"),
        name="app-company-autocomplete",
    ),
    path(
        "app-user-autocomplete-no-create/",
        views.AppUserAutocompleteNoCreate.as_view(),
        name="app-user-autocomplete-no-create",
    ),
    path(
        "app-user-ajax-create/", views.app_user_ajax_create, name="app-user-ajax-create"
    ),
    path(
        "app-user/update/<int:pk>",
        views.AppUserUpdateItemView.as_view(),
        name="app-user-update-item",
    ),
    path(
        "app-company/update/<int:pk>",
        views.AppCompanyUpdateItemView.as_view(),
        name="app-company-update-item",
    ),
    path(
        "attributes/",
        views.FilterableAttributeListView.as_view(),
        name="filterable-attributes-list",
    ),
    path(
        "attributes/update/<int:pk>",
        views.FilterableAttributeUpdateItemView.as_view(),
        name="filterable-attributes-update-item",
    ),
]
