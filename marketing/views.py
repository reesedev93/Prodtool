from urllib.parse import urlencode

import requests
from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone


def home(request):
    return render(request, "marketing-home.html")


def pricing(request):
    return render(request, "pricing.html")


def terms(request):
    return render(request, "terms.html")


def appsumo(request, code):
    base_url = reverse("accounts-join")
    query_string = urlencode({"code": code})
    url = "{}?{}".format(base_url, query_string)
    return redirect(url)


def privacy(request):
    return render(request, "privacy.html")


def data_processing_agreement(request):
    return render(request, "data_processing_agreement.html")


def about(request):
    return render(request, "about.html")


def use_cases(request):
    return render(request, "use-cases.html")


def features(request):
    return render(request, "features.html")


def feature_request(request):
    return render(request, "feature-request.html")


def customer_attributes(request):
    return render(request, "customer-attributes.html")


def collect_feedback(request):
    return render(request, "use-case-collect-feedback.html")


def analyze_feedback(request):
    return render(request, "use-case-analyze-feedback.html")


def prioritize_feedback(request):
    return render(request, "use-case-prioritize-feedback.html")


def use_feedback(request):
    return render(request, "use-case-use-feedback.html")


def close_loop(request):
    return render(request, "use-case-close-loop.html")


def help(request):
    return render(request, "help.html")


def intercom_test_data(request):
    return render(request, "intercom-test-data.html")


def segment_integration(request):
    return render(request, "segment.html")


def intercom_integration(request):
    return render(request, "intercom.html")


def helpscout_integration(request):
    if request.GET.get("utm_campaign", None) == "june_2019_product_update":
        return redirect("marketing-customer-attributes")
    else:
        return render(request, "helpscout.html")


def icp_support(request):
    return render(request, "customers/support.html")


def helpscout_integration_product(request):
    return render(request, "helpscout-product.html")


def intercom_integration_product(request):
    return render(request, "intercom-product.html")


def help_helpscout_integration(request):
    return render(request, "help/helpscout.html")


def help_intercom_integration(request):
    return render(request, "help/intercom.html")


def help_api_integration(request):
    return render(request, "help/api.html")


def slack_integration(request):
    return render(request, "slack.html")


def all_integrations(request):
    querystring = {
        "token": settings.STORYBLOK_API_TOKEN,
        "ct": timezone.now().timestamp(),
        "starts_with": "integrations",
        "sort_by": "name",
        "per_page": 50,
    }

    response = requests.get(
        "https://api.storyblok.com/v1/cdn/stories/", params=querystring
    )

    if response.ok:
        content = response.json()
        print(content)
        return render(request, "all_integrations.html", context=content)
    else:
        raise Http404()


def help_zapier_integration(request):
    return render(request, "zapier.html")


def chrome_extension(request):
    return render(request, "chrome-extension.html")


def send_email(request):
    return render(request, "send-email.html")


def mental_model(request):
    return render(request, "mental-model.html")


def triage(request):
    return render(request, "triage.html")


def product_planning(request):
    return render(request, "product-planning.html")


def blog_index(request):
    return render(request, "blog/index.html")


def blog_savio_segment(request):
    return render(request, "blog/savio-segment-integration.html")


def blog_cs_influence_roadmap(request):
    return render(request, "blog/cs-influence-roadmap.html")


def blog_customer_feedback_guide(request):
    return render(request, "blog/product-leaders-guide-customer-feedback.html")


def blog_track_feature_requests_in_typeform(request):
    return render(request, "blog/track-feature-requests-in-typeform.html")


def blog_tracking_feature_requests_in_intercom(request):
    return render(request, "blog/tracking-feature-requests-in-intercom.html")


def blog_tracking_feature_requests_in_helpscout(request):
    return render(request, "blog/tracking-feature-requests-in-helpscout.html")


def blog_tracking_feature_requests_from_slack(request):
    return render(request, "blog/tracking-feature-requests-from-slack.html")


def blog_tracking_feature_requests_from_hubspot_crm(request):
    return render(request, "blog/tracking-feature-requests-in-hubspot-crm.html")


def blog_using_zapier_to_collect_customer_feedback(request):
    return render(request, "blog/using-zapier-to-collect-customer-feedback.html")


def canny_alternative(request):
    return render(request, "alternatives/canny.html")


def pb_alternative(request):
    return render(request, "alternatives/productboard.html")


def trello_alternative(request):
    return render(request, "alternatives/trello.html")


def uservoice_alternative(request):
    return render(request, "alternatives/uservoice.html")


def aha_alternative(request):
    return render(request, "alternatives/aha.html")


def customer_feedback_playbook(request):
    return render(request, "customer-feedback-playbook/index.html")


def customer_feedback_playbook_why_collect(request):
    return render(request, "customer-feedback-playbook/why-collect.html")


def customer_feedback_playbook_four_systems(request):
    return render(request, "customer-feedback-playbook/four-systems.html")


def headless_cms_fallback(request, slug):
    querystring = {
        "token": settings.STORYBLOK_API_TOKEN,
        "ct": timezone.now().timestamp(),
    }

    response = requests.get(
        f"https://api.storyblok.com/v1/cdn/stories/{slug}", params=querystring
    )

    if response.ok:
        content = response.json()
        template = content["story"]["content"]["django_template"]
        return render(request, template, context=content)
    else:
        raise Http404()


def ahrefs_verification(request):
    return HttpResponse(
        "ahrefs-site-verification_a92626a216c718797d3e1c4efe28680e2e63a77abdfe986118afb39b1558977d"
    )
