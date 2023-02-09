import random
import uuid
from datetime import timedelta

import stripe
from celery import shared_task
from django.conf import settings
from django.core.mail import mail_admins
from django.db.models import Count, Q
from django.template import loader
from django.utils import timezone
from sentry_sdk import capture_exception

from .models import Subscription, User


@shared_task
def send_admin_subscription_summary_email():
    """
    Sends a summary of our subscriptions so we know what's what
    """

    cutoff = timezone.now() - timedelta(days=7)

    trialing_subs = Subscription.objects.filter(status=Subscription.STATUS_TRIALING)
    trialing_subs = trialing_subs.annotate(
        total_feedback=Count("customer__feedback"),
        recent_feedback=Count(
            "customer__feedback", filter=Q(customer__feedback__created__gte=cutoff)
        ),
    ).order_by("-recent_feedback")

    paying_subs = Subscription.objects.filter(
        status=Subscription.STATUS_ACTIVE, card_on_file=True, next_mrr_payment__gt=0
    )
    paying_subs = paying_subs.annotate(
        total_feedback=Count("customer__feedback"),
        recent_feedback=Count(
            "customer__feedback", filter=Q(customer__feedback__created__gte=cutoff)
        ),
    ).order_by("-recent_feedback")

    free_subs = Subscription.objects.filter(
        next_mrr_payment=0, status=Subscription.STATUS_ACTIVE
    )
    free_subs = free_subs.annotate(
        total_feedback=Count("customer__feedback"),
        recent_feedback=Count(
            "customer__feedback", filter=Q(customer__feedback__created__gte=cutoff)
        ),
    ).order_by("-recent_feedback")

    gone_bad_subs = (
        Subscription.objects.filter(updated__gte=cutoff)
        .exclude(status__in=(Subscription.STATUS_ACTIVE, Subscription.STATUS_TRIALING))
        .annotate(
            total_feedback=Count("customer__feedback"),
            recent_feedback=Count(
                "customer__feedback", filter=Q(customer__feedback__created__gte=cutoff)
            ),
        )
    )

    context = {
        "cutoff": cutoff,
        "host": settings.HOST,
        "trialing_subs": trialing_subs,
        "gone_bad_subs": gone_bad_subs,
        "free_subs": free_subs,
        "paying_subs": paying_subs,
    }

    subject = "[Savio]: Weekly Subscription Summary"

    txt_message = "This is an HTML email sucker!"
    html_message = loader.render_to_string(
        "email/weekly_subscription_summary.html", context
    )

    mail_admins(subject, txt_message, html_message=html_message)


@shared_task
def sync_feedback_counts_and_mrr_with_stripe():
    subs = Subscription.objects.filter(status=Subscription.STATUS_ACTIVE)
    subs = subs.annotate(total_feedback=Count("customer__feedback"))

    for sub in subs:
        stripe.api_key = settings.STRIPE_API_KEY
        stripe_subscription = stripe.Subscription.retrieve(sub.stripe_subscription_id)

        # We're looping through all subscription items in this code
        # (a Stripe subscription can have multiple "items". An item
        # is an instance of a plan).  We need to find the SubscriptionItem
        # that belongs to the tiered plan.  This is because usage hangs
        # off the SubscriptionItem, not the Subscription.  When we find the
        # SubscriptionItem we use Stripe's usage API to send in feedback count.

        print(sub.stripe_subscription_id)
        for ss in stripe_subscription["items"]["data"]:
            sub.update_next_mrr_payment(stripe_subscription)
            if ss["plan"]["id"] == settings.PLAN_TIERED:
                try:
                    stripe.SubscriptionItem.create_usage_record(
                        ss["id"],
                        quantity=sub.total_feedback,
                        timestamp=timezone.now(),
                        action="set",
                        idempotency_key=str(uuid.uuid1()),
                    )
                except Exception as e:
                    capture_exception(e)


@shared_task
def send_signup_survey_email(user_id):
    user = User.objects.get(pk=user_id)

    subject_candidates = (
        f"{user.first_name}, a question",
        f"Question for you {user.first_name}",
    )

    subject = random.choice(subject_candidates)
    txt_message = loader.render_to_string(
        "email/signup_survey.txt", {"first_name": user.first_name,}
    )

    user.email_user(subject, txt_message, "Kareem Mayan <k@savio.io>")
