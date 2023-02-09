"""marketing URL Configuration

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
from django.contrib.sitemaps.views import sitemap
from django.urls import path, re_path

import marketing.views as views
from marketing.sitemaps import StaticSitemap

# Dictionary containing your sitemap classes
sitemaps = {
    "static": StaticSitemap(),
}
urlpatterns = [
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("", views.home, name="marketing-home"),
    path("pricing/", views.pricing, name="marketing-pricing"),
    path("terms/", views.terms, name="marketing-terms"),
    path("privacy/", views.privacy, name="marketing-privacy"),
    path(
        "data-processing-agreement/",
        views.data_processing_agreement,
        name="marketing-data-processing-agreement",
    ),
    path("appsumo/<code>", views.appsumo, name="marketing-appsumo"),
    path("help/", views.help, name="marketing-help"),
    path("help/zapier/", views.help_zapier_integration, name="marketing-help-zapier"),
    path(
        "help/helpscout/",
        views.help_helpscout_integration,
        name="marketing-help-helpscout",
    ),
    path(
        "help/intercom/",
        views.help_intercom_integration,
        name="marketing-help-intercom",
    ),
    path("help/api/", views.help_api_integration, name="marketing-help-api"),
    path("features/", views.features, name="marketing-features"),
    path(
        "customer-attributes/",
        views.customer_attributes,
        name="marketing-customer-attributes",
    ),
    path("feature-request/", views.feature_request, name="marketing-feature-request"),
    path("use-cases/", views.use_cases, name="marketing-use-cases"),
    path(
        "use-cases/collect-feedback/",
        views.collect_feedback,
        name="marketing-use-cases-collect-feedback",
    ),
    path(
        "use-cases/prioritize-feedback/",
        views.prioritize_feedback,
        name="marketing-use-cases-prioritize-feedback",
    ),
    path(
        "use-cases/use-feedback/",
        views.use_feedback,
        name="marketing-use-cases-use-feedback",
    ),
    path(
        "use-cases/close-the-loop/",
        views.close_loop,
        name="marketing-use-cases-close-loop",
    ),
    path("about/", views.about, name="marketing-about"),
    path("send-email/", views.send_email, name="marketing-send-email"),
    path("triaging-customer-feedback/", views.triage, name="marketing-triage"),
    path(
        "product-planning/", views.product_planning, name="marketing-product-planning"
    ),
    path("mental-model/", views.mental_model, name="marketing-mental-model"),
    path(
        "chrome-extension/", views.chrome_extension, name="marketing-chrome-extension"
    ),
    path(
        "integrations/segment/",
        views.segment_integration,
        name="marketing-integrations-segment",
    ),
    path(
        "integrations/helpscout/",
        views.helpscout_integration,
        name="marketing-integrations-helpscout",
    ),
    path(
        "integrations/helpscout/product/",
        views.helpscout_integration_product,
        name="marketing-integrations-helpscout-product",
    ),
    path(
        "integrations/intercom/",
        views.intercom_integration,
        name="marketing-integrations-intercom",
    ),
    path(
        "integrations/intercom/product/",
        views.intercom_integration_product,
        name="marketing-integrations-intercom-product",
    ),
    path(
        "integrations/slack/",
        views.slack_integration,
        name="marketing-integrations-slack",
    ),
    path(
        "integrations/all/", views.all_integrations, name="marketing-integrations-all"
    ),
    path(
        "intercom/test-data",
        views.intercom_test_data,
        name="marketing-intercom-test-data",
    ),
    path(
        "blog/track-feature-requests-from-typeform-surveys/",
        views.blog_track_feature_requests_in_typeform,
        name="marketing-blog-track-feature-requests-in-typeform",
    ),
    path("blog/", views.blog_index, name="marketing-blog-index"),
    path(
        "blog/savio-segment-integration/",
        views.blog_savio_segment,
        name="marketing-blog-savio-segment",
    ),
    path(
        "blog/product-leaders-guide-customer-feedback/",
        views.blog_customer_feedback_guide,
        name="marketing-blog-feedback-guide",
    ),
    path(
        "blog/why-customer-success-is-influencing-product-roadmaps/",
        views.blog_cs_influence_roadmap,
        name="marketing-blog-cs-influence-roadmap",
    ),
    path(
        "blog/tracking-feature-requests-in-intercom/",
        views.blog_tracking_feature_requests_in_intercom,
        name="marketing-blog-tracking-feature-requests-in-intercom",
    ),
    path(
        "blog/tracking-feature-requests-in-helpscout/",
        views.blog_tracking_feature_requests_in_helpscout,
        name="marketing-blog-tracking-feature-requests-in-helpscout",
    ),
    path(
        "blog/tracking-feature-requests-from-slack/",
        views.blog_tracking_feature_requests_from_slack,
        name="marketing-blog-tracking-feature-requests-from-slack",
    ),
    path(
        "blog/tracking-feature-requests-from-hubspot-crm/",
        views.blog_tracking_feature_requests_from_hubspot_crm,
        name="marketing-blog-tracking-feature-requests-from-hubspot-crm",
    ),
    path(
        "blog/using-zapier-to-collect-customer-feedback/",
        views.blog_using_zapier_to_collect_customer_feedback,
        name="marketing-blog-using-zapier-to-collect-customer-feedback",
    ),
    path("customers/support", views.icp_support, name="marketing-icp-support"),
    path(
        "compare/canny-vs-savio/",
        views.canny_alternative,
        name="marketing-alternatives-canny",
    ),
    path(
        "compare/productboard-vs-savio/",
        views.pb_alternative,
        name="marketing-alternatives-pb",
    ),
    path(
        "compare/trello-vs-savio/",
        views.trello_alternative,
        name="marketing-alternatives-trello",
    ),
    path(
        "compare/uservoice-vs-savio/",
        views.uservoice_alternative,
        name="marketing-alternatives-uservoice",
    ),
    path(
        "compare/aha-vs-savio/",
        views.aha_alternative,
        name="marketing-alternatives-aha",
    ),
    path(
        "compare/aha-vs-savio/",
        views.aha_alternative,
        name="marketing-alternatives-aha",
    ),
    path(
        "customer-feedback/",
        views.customer_feedback_playbook,
        name="marketing-customer-feedback-playbook",
    ),
    path(
        "customer-feedback/why-collect-customer-feedback",
        views.customer_feedback_playbook_why_collect,
        name="marketing-customer-feedback-playbook-why-collect",
    ),
    path(
        "customer-feedback/how-to-organize-user-feedback",
        views.customer_feedback_playbook_four_systems,
        name="marketing-customer-feedback-playbook-four-systems",
    ),
    path(
        "ahrefs_a92626a216c718797d3e1c4efe28680e2e63a77abdfe986118afb39b1558977d",
        views.ahrefs_verification,
        name="marketing-ahrefs-verification",
    ),
    re_path(
        r"^(?!app|!admin)(?P<slug>[a-zA-Z0-9\-/]+)/$",
        views.headless_cms_fallback,
        name="marketing-headless-cms-fallback",
    ),
]
