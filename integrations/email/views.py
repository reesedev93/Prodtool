import hashlib
import hmac
import re

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from accounts.models import User
from appaccounts.models import AppUser
from feedback.models import Feedback


@csrf_exempt
def receive_email_webhook(request):
    # This works in conjunction with Mailgun's 'Routes' feature.
    # If you want to test this checkout "Ryan's Testing Route"
    # to see how to setup your own test route. You'll also need
    # to use the Django admin to manually change your users
    # create_feedback_email property to include your debug prefix
    # so it matches what the debug route in mailgun is checking for.
    if request.method == "POST" and request.POST.get("recipient"):
        timestamp = request.POST.get("timestamp", "")
        token = request.POST.get("token", "")
        signature = request.POST.get("signature", "")
        msg = "{}{}".format(timestamp, token)
        hmac_digest = hmac.new(
            key=settings.MAILGUN_API_KEY.encode("ascii"),
            msg=msg.encode("ascii"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(signature, hmac_digest):
            to = request.POST.get("recipient")

            to_print = [
                "From",
                "In-Reply-To",
                "References",
                "Sender",
                "To",
                "X-Mailgun-Variables",
                "from",
                "sender",
                "signature",
                "stripped-signature",
            ]
            for key in to_print:
                print(f"{key}: {request.POST.get(key, '')}")

            try:
                # To avoid confusion we always force the secret to be lowercase.
                # We also migrated everything to lowercase but on the of chance
                # that someone saved one with mixed case lets just do a case
                # insenstive lookup here.
                user = User.objects.get(create_feedback_email__iexact=to)
                subject = request.POST.get("subject", "")
                body = request.POST.get("body-plain", "")
                source_appuser = get_feedback_submitter_from_body(body, user)
                Feedback.objects.get_or_create(
                    customer=user.customer,
                    created_by=user,
                    problem=f"{subject}\n\n{body}",
                    defaults={"user": source_appuser,},
                )
            except User.DoesNotExist:
                return HttpResponse(status=406)
        else:
            return HttpResponse(status=406)
    return HttpResponse(status=200)


# Non-view functions
def get_feedback_submitter_from_body(body, user):
    """
    Gets our best guess of who the AppUser is that submitted this
    feedback.

    We've got a hint a couple of hints:
    1. It's probably not the direct sender.
    2. It's probably not an email from the same domain as the sender.

    We assume the first email from a domain different than the User
    that has an existing AppUser is the 'real' submitter.
    """
    candidate_emails = get_email_addresses(body)
    users_domain = user.email.split("@")[1]
    appuser = None
    for email in candidate_emails:
        domain = email.split("@")[1]
        if domain != users_domain:
            appuser, created = AppUser.objects.get_or_create(
                customer=user.customer, email__iexact=email, defaults={"email": email,}
            )
    return appuser


def get_email_addresses(text):
    """
    Returns a list of unique email address fround in 'text'.

    There are a lot of differnet ways we might try and do this.
    We could probably use a library like:
    https://github.com/zapier/email-reply-parser
    https://github.com/mailgun/talon/tree/master/talon/signature
    """

    # There are a lot of email regexs you could dream up but
    # we just want something simple that won't inadvertanly
    # include stuff like '<' or spaces.
    # E.g. given '> From: Abbey Weber <abbey.weber@housecallpro.com>\r'
    # it will return just abbey.weber@housecallpro.com.
    email_regex = re.compile(r"[^\s<>:]+@[^\s<>:]+\.[^\s<>:]+")

    return set(email_regex.findall(text))
