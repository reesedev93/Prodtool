from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.deprecation import MiddlewareMixin

from accounts.models import User


class PayOrNoAccessMiddleware(MiddlewareMixin):
    def __init__(self, get_response=None):
        super().__init__(get_response)

    def process_response(self, request, response):
        if request.user.is_authenticated and request.user.customer.has_subscription():
            has_inactive_subscription = (
                request.user.customer.subscription.inactive()
                or request.user.customer.subscription.over_free_feedback_limit_and_needs_to_pay()
            )
        else:
            has_inactive_subscription = False

        full_path = request.get_full_path()
        if has_inactive_subscription:
            cc_url = reverse_lazy("accounts-settings-add-credit-card") + "?add_card=1"
            allowed_urls = (
                cc_url,
                reverse_lazy("accounts-no-payment-source-on-file"),
            )
            if (full_path not in allowed_urls) and ("/app/" in full_path):
                # Make em pay!
                if request.user.role == User.ROLE_OWNER:
                    return redirect(cc_url)
                else:
                    return redirect("accounts-no-payment-source-on-file")

        # All good just return the response
        return response
