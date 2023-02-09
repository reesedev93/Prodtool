import secrets
import string
import uuid
from datetime import datetime, timedelta

import stripe
from django.conf import settings
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import EmailValidator
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.template import loader
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.authtoken.models import Token


def validate_domain(domain):
    bad_domains = [
        "aim.com",
        "aol.com",
        "email.com",
        "gmail.com",
        "googlemail.com",
        "hotmail.com",
        "hushmail.com",
        "msn.com",
        "mail.ru",
        "mailinator.com",
        "live.com",
        "yahoo.com",
        "outlook.com",
    ]

    if domain.strip() in bad_domains:
        raise ValidationError("You must use a company email address.",)

    if not EmailValidator().validate_domain_part(domain):
        raise ValidationError("Invalid domain.")
    return domain


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_auth_token(sender, instance=None, created=False, **kwargs):
    if created:
        Token.objects.create(user=instance)


class Customer(models.Model):
    name = models.CharField(max_length=255)
    whitelisted_domain = models.CharField(
        blank=True, unique=True, null=True, max_length=63, validators=[validate_domain]
    )
    submitters_can_create_features = models.BooleanField(default=True)
    first_referer = models.TextField(blank=True, default="")
    first_landing_page = models.TextField(blank=True, default="")

    last_referer = models.TextField(blank=True, default="")
    last_landing_page = models.TextField(blank=True, default="")

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    def __str__(self):
        return self.name

    def has_subscription(self):
        try:
            self.subscription
            return True
        except Subscription.DoesNotExist:
            return False

    def friendly_plan_name(self):
        try:
            self.subscription
            return self.subscription.get_plan_display()
        except Subscription.DoesNotExist:
            return "No Subscription"

    def friendly_billing_amount(self):
        try:
            self.subscription
            return self.subscription.get_billing_amount()
        except Subscription.DoesNotExist:
            return 0

    def current_plan_feedback_count(self):
        # ONLY WORKS FOR PER-SEAT PLANS

        # Return max feedback count of plan that allows current feedback count
        # For example if current count is 21, returns 100
        current_count = self.total_feedback_count()

        # Get index of plan that allows current feedback count
        index_array = []

        for index, max_feedback in enumerate(Subscription.PLAN_TIERED_FEEDBACK_COUNTS):
            if current_count >= max_feedback:
                index_array.append((index, max_feedback))
                break

        if index_array:
            max_feedback_for_plan = Subscription.PLAN_TIERED_FEEDBACK_COUNTS[
                index_array[0][0]
            ]
        else:
            max_feedback_for_plan = Subscription.PLAN_TIERED_FEEDBACK_COUNTS[0]
        return max_feedback_for_plan

    def current_plan_price(self):
        # ONLY WORKS FOR PER-SEAT PLANS

        # Return dollar amount of plan that allows current feedback count
        # For example if current count is 21, returns $49 (supports 20-100 feedback)
        current_count = self.total_feedback_count()
        # Get index of plan that allows current feedback count

        # Get index of plan that allows current feedback count
        index_array = []

        for index, max_feedback in enumerate(Subscription.PLAN_TIERED_FEEDBACK_COUNTS):
            if current_count >= max_feedback:
                index_array.append((index, max_feedback))
                break

        if index_array:
            price = Subscription.PLAN_TIERED_PRICES[index_array[0][0]]
        else:
            price = Subscription.PLAN_TIERED_PRICES[0]
        return price

    def next_plan_feedback_count(self):
        # ONLY WORKS FOR PER-SEAT PLANS

        # Return max feedback count of plan that allows current feedback count
        # For example if current count is 21, returns 100
        current_count = self.total_feedback_count()

        # Get index of plan that allows current feedback count
        index_array = []

        for index, max_feedback in enumerate(Subscription.PLAN_TIERED_FEEDBACK_COUNTS):
            if current_count < max_feedback:
                index_array.append((index, max_feedback))
                break

        if index_array:
            next_plan_amount = Subscription.PLAN_TIERED_FEEDBACK_COUNTS[
                index_array[0][0]
            ]
        else:
            next_plan_amount = Subscription.PLAN_TIERED_FEEDBACK_COUNTS[0]
        return next_plan_amount

    def next_plan_price(self):
        # ONLY WORKS FOR PER-SEAT PLANS

        # Return dollar amount of plan that allows current feedback count
        # For example if current count is 21, returns $49 (supports 20-100 feedback)
        current_count = self.total_feedback_count()

        # Get index of plan that allows current feedback count
        index_array = []

        for index, max_feedback in enumerate(Subscription.PLAN_TIERED_FEEDBACK_COUNTS):
            if current_count < max_feedback:
                index_array.append((index, max_feedback))
                break

        return Subscription.PLAN_TIERED_PRICES[index_array[0][0]]

    def newest_feedback_created_one_hour_ago(self):
        if self.newest_feedback():
            newest_feedback_created = self.newest_feedback().created
        else:
            newest_feedback_created = timezone.now()
        return (
            round((timezone.now() - newest_feedback_created).total_seconds() / 60) >= 60
        )

    def newest_feedback(self):
        from feedback.models import (
            Feedback,
        )  # Avoid circular import. Move to a context processor?

        return Feedback.objects.filter(customer=self).order_by("created").last()

    def total_feedback_count(self):
        from feedback.models import (
            Feedback,
        )  # Avoid circular import. Move to a context processor?

        return Feedback.objects.filter(customer=self).count()

    def feedback_submitted_last_7_days_count(self):
        from feedback.models import (
            Feedback,
        )  # Avoid circular import. Move to a context processor?

        seven_days_ago = timezone.now() - timedelta(days=7)
        return Feedback.objects.filter(
            customer=self, created__gte=seven_days_ago
        ).count()

    def untriaged_feedback_count(self):
        from feedback.models import (
            Feedback,
        )  # Avoid circular import. Move to a context processor?

        return Feedback.objects.filter(customer=self, state=Feedback.ACTIVE).count()

    def pending_feedback_count(self):
        from feedback.models import Feedback

        return Feedback.objects.filter(customer=self, state=Feedback.PENDING).count()

    def shipped_feature_request_count(self):
        from feedback.models import FeatureRequest

        return FeatureRequest.objects.filter(
            customer=self, state=FeatureRequest.SHIPPED
        ).count()

    def onboarding_percent_complete(self):
        return int(OnboardingTask.objects.percent_complete(self) * 100)

    def users(self):
        return User.objects.filter(customer=self)

    def num_users(self):
        return self.users().count()

    def owner(self):
        return self.users().filter(role=User.ROLE_OWNER).first()

    def turn_off_whitelist(self):
        self.whitelisted_domain = None
        self.save()


class Invitation(models.Model):
    ROLE_OWNER = "OWNER"
    ROLE_ADMIN = "ADMIN"
    ROLE_SUBMITTER = "SUBMITTER"
    ROLE_CHOICES = (
        (ROLE_OWNER, "Owner"),
        (ROLE_ADMIN, "Admin"),
        (ROLE_SUBMITTER, "Submitter"),
    )

    email = models.EmailField(_("email address"), unique=True, blank=True)
    expired = models.BooleanField(default=False)
    customer = models.ForeignKey(Customer, null=True, on_delete=models.CASCADE)
    role = models.CharField(choices=ROLE_CHOICES, default=ROLE_SUBMITTER, max_length=30)

    def __str__(self):
        return self.email

class SubscriptionManager(models.Manager):
    def create_stripe_subscription(self, user, plan):
        stripe.api_key = settings.STRIPE_API_KEY
        stripe_customer = stripe.Customer.create(email=user.email)

        stripe_subscription = stripe.Subscription.create(
            customer=stripe_customer.id, trial_from_plan=True, items=[{"price": plan}],
        )

        if stripe_subscription.status == "trialing":
            status = Subscription.STATUS_TRIALING
        else:
            status = Subscription.STATUS_ACTIVE

        if stripe_subscription.trial_end:
            trial_end = datetime.utcfromtimestamp(stripe_subscription.trial_end)
        else:
            trial_end = None

        subs = self.get_or_create(
            customer=user.customer,
            plan=plan,
            stripe_customer_id=stripe_customer.id,
            stripe_subscription_id=stripe_subscription.id,
            card_on_file=False,
            status=status,
            plan_type=Subscription.PLAN_TYPE_FEATURE_TIERED,
            trial_end_date=trial_end,
        )

        subs[0].update_next_mrr_payment(stripe_subscription)


class Subscription(models.Model):

    PLAN_TIERED_PRICES = [0, 49, 69, 89, 109, 129, 149, 169, 189, 199, 299, 399, 499]
    PLAN_TIERED_FEEDBACK_COUNTS = [
        20,
        100,
        200,
        300,
        400,
        500,
        600,
        700,
        800,
        1000,
        2000,
        3000,
        4000,
    ]

    PLAN_TIERED = settings.PLAN_TIERED
    PLAN_EARLY_ADOPTER_20_PER_USER = settings.PLAN_EARLY_ADOPTER_20_PER_USER
    PLAN_SMB_49_PER_USER = settings.PLAN_SMB_49_PER_USER
    PLAN_MID_99_PER_USER = settings.PLAN_MID_99_PER_USER
    PLAN_1_USER_FREE = settings.PLAN_1_USER_FREE
    PLAN_3_USERS_25 = settings.PLAN_3_USERS_25
    PLAN_UNLIMITED_USERS_49 = settings.PLAN_UNLIMITED_USERS_49
    PLAN_LIFETIME_APPSUMO_99 = settings.PLAN_LIFETIME_APPSUMO_99

    FEATURE_TIERED_PLAN_CHOICES = (
        (PLAN_1_USER_FREE, "Free for 1 user"),
        (PLAN_3_USERS_25, "SMB - $25/m for up to 3 users"),
        (PLAN_UNLIMITED_USERS_49, "Growth - $49/m for unlimited users"),
    )

    FEATURE_TIERED_USERS_PER_PLAN = {
        PLAN_1_USER_FREE: "1",
        PLAN_3_USERS_25: "3",
        PLAN_UNLIMITED_USERS_49: "Unlimited",
    }

    PLAN_CHOICES = (
        (PLAN_TIERED, "Tiered pricing"),
        (PLAN_EARLY_ADOPTER_20_PER_USER, "Early Adopter - $20/user per month"),
        (PLAN_SMB_49_PER_USER, "Small - $49/user per month"),
        (PLAN_MID_99_PER_USER, "Medium - $99/user per month"),
        (PLAN_1_USER_FREE, "Free for 1 user"),
        (PLAN_3_USERS_25, "SMB - $25/m for up to 3 users"),
        (PLAN_UNLIMITED_USERS_49, "Growth - $49/m for unlimited users"),
        (PLAN_LIFETIME_APPSUMO_99, "AppSumo - $99 for for lifetime access"),
    )

    STATUS_TRIALING = "trialing"
    STATUS_ACTIVE = "active"
    STATUS_INCOMPLETE = "incomplete"
    STATUS_INCOMPLETE_EXPIRED = "incomplete_expired"
    STATUS_PAST_DUE = "past_due"
    STATUS_CANCELED = "canceled"
    STATUS_UNPAID = "unpaid"

    STATUS_CHOICES = (
        (STATUS_TRIALING, "Trialing"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_INCOMPLETE, "Incomplete"),
        (STATUS_INCOMPLETE_EXPIRED, "Incomplete Expired"),
        (STATUS_PAST_DUE, "Past Due"),
        (STATUS_CANCELED, "Canceled"),
        (STATUS_UNPAID, "Unpaid"),
    )

    PLAN_TYPE_PER_SEAT = "per_seat"
    PLAN_TYPE_USAGE_TIERED = "usage_tiered"
    PLAN_TYPE_FEATURE_TIERED = "feature_tiered"

    PLAN_TYPE_CHOICES = (
        (PLAN_TYPE_PER_SEAT, "Per Seat"),
        (PLAN_TYPE_USAGE_TIERED, "Usage Tiered"),
        (PLAN_TYPE_FEATURE_TIERED, "Feature Tiered"),
    )

    stripe_customer = None

    customer = models.OneToOneField(Customer, on_delete=models.CASCADE)

    plan = models.CharField(choices=PLAN_CHOICES, max_length=255)
    stripe_customer_id = models.CharField(max_length=255)
    stripe_subscription_id = models.CharField(max_length=255)
    next_mrr_payment = models.FloatField(null=True, blank=True)
    trial_end_date = models.DateTimeField(null=True, blank=True)
    card_on_file = models.BooleanField(default=False)
    status = models.CharField(choices=STATUS_CHOICES, max_length=30)
    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)
    is_per_seat_plan = models.BooleanField(default=False)
    plan_type = models.CharField(
        choices=PLAN_TYPE_CHOICES, max_length=30, default="feature_tiered"
    )

    objects = SubscriptionManager()

    def is_plan_per_seat(self):
        return self.plan_type == Subscription.PLAN_TYPE_PER_SEAT

    def is_usage_tiered(self):
        return self.plan_type == Subscription.PLAN_TYPE_USAGE_TIERED

    def is_feature_tiered(self):
        return self.plan_type == Subscription.PLAN_TYPE_FEATURE_TIERED

    def plan_users(self):
        if self.is_plan_per_seat() or self.is_usage_tiered():
            return "Unlimited"
        else:
            return Subscription.FEATURE_TIERED_USERS_PER_PLAN[self.plan]

    def is_feature_tiered_on_free_plan(self):
        return self.is_feature_tiered() and self.on_free_plan()

    def on_free_plan(self):
        return self.plan == Subscription.PLAN_1_USER_FREE

    def is_recurring(self):
        return not self.is_one_time()

    def is_one_time(self):
        return self.plan == Subscription.PLAN_LIFETIME_APPSUMO_99

    def trialing(self):
        return self.status == Subscription.STATUS_TRIALING

    def can_use_autojoin(self):
        return (
            self.plan == Subscription.PLAN_UNLIMITED_USERS_49
            or self.plan == Subscription.PLAN_LIFETIME_APPSUMO_99
            or self.is_plan_per_seat()
            or self.is_usage_tiered()
        )

    def get_plan_display(self):
        choices = dict(Subscription.PLAN_CHOICES)
        return choices[self.plan]

    def inactive(self):
        # subs that are not trialing or active will be inactive.
        # Freemium customers can be inactive if they've paid and their card has subsquently failed.
        # otherwise, it's most likely per-seat plans whose trial has expired that
        # will be inactive.
        good_sub_states = (Subscription.STATUS_TRIALING, Subscription.STATUS_ACTIVE)
        return self.status not in good_sub_states

    def over_free_feedback_limit_and_needs_to_pay(self):
        # This method returns true if user has no card on file or an inactive sub,
        # Is usage tiered, is over free feedback limit, and last feedback has been
        # created over an hour ago
        return (
            (self.no_card_on_file() or self.inactive())
            and self.is_usage_tiered()
            and self.over_free_feedback_limit()
            and self.customer.newest_feedback_created_one_hour_ago()
        )

    def under_free_feedback_limit(self):
        return self.customer.total_feedback_count() <= 20

    def over_free_feedback_limit(self):
        return self.customer.total_feedback_count() > 20

    def no_card_on_file(self):
        return not self.card_on_file

    def can_add_more_users(self):
        if self.is_feature_tiered():
            num_users = self.customer.num_users()
            if (self.plan == Subscription.PLAN_3_USERS_25 and num_users >= 3) or (
                self.plan == Subscription.PLAN_1_USER_FREE and num_users >= 1
            ):
                return False
        return True

    def credit_card_required(self):
        return self.trialing() and not self.card_on_file and not self.on_free_plan()

    def days_left_in_trial(self):
        days_left = (self.trial_end_date - timezone.now()).days + 1
        return days_left

    def add_tokenized_card(self, token):
        stripe.api_key = settings.STRIPE_API_KEY
        stripe.Customer.modify(self.stripe_customer_id, source=token)
        self.card_on_file = True
        self.save()

    def get_stripe_customer(self):
        if not self.stripe_customer:
            stripe.api_key = settings.STRIPE_API_KEY
            self.stripe_customer = stripe.Customer.retrieve(self.stripe_customer_id)
        return self.stripe_customer

    def get_default_source(self):
        # BUGBUG: if our code adds the default source it will be a card
        # but... you can do it in the UI and it might end up being a
        # source not a card (sources abstract different payment types).
        # Our code assumes it's a card in which case you might get bad
        # behaviour as cards and sources don't have the same shape.
        stripe_customer = self.get_stripe_customer()
        default_source_id = stripe_customer.get("default_source", "")
        default_source = dict()
        sources = stripe_customer.get("sources").get("data")
        for source in sources:
            if source.id == default_source_id:
                default_source = source
                break
        return default_source

    def get_cc_last_four_digits(self):
        return self.get_default_source().get("last4", "XXXX")

    def get_cc_brand(self):
        return self.get_default_source().get("brand", "XXXX")

    def get_cc_expiry(self):
        default_source = self.get_default_source()
        if default_source:
            try:
                expiry = f"{default_source.exp_month}/{default_source.exp_year}"
            except AttributeError:
                # See note in get_default_source()
                expiry = "MM/YYYY"
        else:
            expiry = "MM/YYYY"
        return expiry

    def get_next_billing_date(self):
        stripe_customer = self.get_stripe_customer()

        try:
            current_period_end = stripe_customer["subscriptions"]["data"][0][
                "current_period_end"
            ]

            billing_date = datetime.fromtimestamp(current_period_end)
        except (KeyError, IndexError):
            billing_date = None
        return billing_date

    def get_billing_amount(self):
        if self.next_mrr_payment:
            return self.next_mrr_payment / 100.0
        else:
            return 0

    def total_paying_users(self):
        return (
            User.objects.filter(customer=self.customer)
            .exclude(role=User.ROLE_SUBMITTER)
            .count()
        )

    # If number of users in Stripe != number of users in system, and we're on a per-seat plan,
    # update number of users in Stripe to number of users in system.
    def sync_stripe_subscription_quantity(self):
        stripe.api_key = settings.STRIPE_API_KEY
        stripe_subscription = stripe.Subscription.retrieve(self.stripe_subscription_id)
        if (
            stripe_subscription["quantity"] != self.total_paying_users()
            and self.is_plan_per_seat()
        ):
            stripe.Subscription.modify(
                self.stripe_subscription_id, quantity=self.total_paying_users()
            )

    # Updates subscription.next_mrr_payment field in our db.
    def update_next_mrr_payment(self, stripe_sub):
        if self.is_plan_per_seat():
            quantity = stripe_sub["quantity"]
            amount = stripe_sub["plan"]["amount"]
            billing_amount = quantity * amount
            self.next_mrr_payment = billing_amount
            self.save()
        else:
            # Works for both usage tiered and feature tiered
            next_invoice = stripe.Invoice.upcoming(customer=stripe_sub["customer"])
            self.next_mrr_payment = next_invoice["total"]
            self.save()

    def has_payment_source(self):
        return len(self.get_stripe_customer()["sources"]["data"]) > 0

    def create_new_stripe_subscription(self, plan, trial=False):
        # If they've canceled their sub this lets us make a new stripe
        # sub and save it in one of our subs.
        stripe.api_key = settings.STRIPE_API_KEY

        stripe_subscription = stripe.Subscription.create(
            customer=self.stripe_customer_id, trial_from_plan=trial, plan=plan,
        )
        self.plan = plan
        self.stripe_subscription_id = stripe_subscription.id
        self.status = stripe_subscription["status"]
        if stripe_subscription.trial_end:
            self.trial_end_date = datetime.utcfromtimestamp(
                stripe_subscription.trial_end
            )

        # Hardcoded because you'll only be able to create feature tiered plans
        # Going fwd.
        self.plan_type = Subscription.PLAN_TYPE_FEATURE_TIERED
        self.card_on_file = self.has_payment_source()
        self.save()
        self.update_next_mrr_payment(stripe_subscription)
        return stripe_subscription

    def modify_stripe_subscription(self, new_plan_id):
        stripe.api_key = settings.STRIPE_API_KEY
        stripe_subscription = stripe.Subscription.retrieve(self.stripe_subscription_id)

        # Right now if a customer downgrades, we give them a credit
        new_stripe_subscription = stripe.Subscription.modify(
            stripe_subscription.id,
            cancel_at_period_end=False,
            proration_behavior="always_invoice",
            items=[
                {
                    "id": stripe_subscription["items"]["data"][0].id,
                    "price": new_plan_id,
                }
            ],
        )

        self.plan = new_plan_id
        self.status = new_stripe_subscription["status"]
        if new_stripe_subscription.trial_end:
            self.trial_end_date = datetime.utcfromtimestamp(
                stripe_subscription.trial_end
            )

        self.card_on_file = self.has_payment_source()
        self.save()
        self.update_next_mrr_payment(new_stripe_subscription)
        return new_stripe_subscription

    def has_non_canceled_stripe_subscription(self):
        stripe.api_key = settings.STRIPE_API_KEY
        stripe_customer = stripe.Customer.retrieve(self.stripe_customer_id)
        return len(stripe_customer["subscriptions"]["data"]) > 0


class MyUserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """
        Create and save a user with the given email, and password.
        """
        if not email:
            raise ValueError("The given email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class Discount(models.Model):
    code = models.CharField(max_length=255, unique=True)
    promo_text = models.CharField(max_length=255)
    plan = models.CharField(max_length=255)
    subscription = models.OneToOneField(
        Subscription, on_delete=models.CASCADE, null=True
    )  # If null, code has not been redeemed
    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    # one-time method to generate codes.  Hardcoded to AppSumo for now.
    def generate_appsumo_codes(num):
        for x in range(num):
            code = "AS99" + uuid.uuid4().hex.upper()
            Discount.objects.create(
                code=code,
                promo_text="AppSumo $99 Lifetime Access",
                plan=Subscription.PLAN_LIFETIME_APPSUMO_99,
            )


class User(AbstractBaseUser, PermissionsMixin):
    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    SUPPORT = "SUPPORT"
    PRODUCT = "PRODUCT"
    SALES = "SALES"
    CUSTOMER_SUCCESS = "CUSTOMER_SUCCESS"
    MARKETING = "MARKETING"
    OTHER = "OTHER"

    JOB_CHOICES = (
        (SUPPORT, "Support"),
        (PRODUCT, "Product"),
        (SALES, "Sales"),
        (CUSTOMER_SUCCESS, "Customer Success"),
        (MARKETING, "Marketing"),
        (OTHER, "Other"),
    )

    ROLE_OWNER = "OWNER"
    ROLE_ADMIN = "ADMIN"
    ROLE_SUBMITTER = "SUBMITTER"
    ROLE_ANY = (ROLE_OWNER, ROLE_ADMIN, ROLE_SUBMITTER)
    ROLE_OWNER_OR_ADMIN = (ROLE_OWNER, ROLE_ADMIN)

    ROLE_CHOICES = (
        (ROLE_OWNER, "Owner"),
        (ROLE_ADMIN, "Admin"),
        (ROLE_SUBMITTER, "Submitter"),
    )

    email = models.EmailField(_("email address"), unique=True, blank=True)
    customer = models.ForeignKey(Customer, null=True, on_delete=models.CASCADE)
    role = models.CharField(choices=ROLE_CHOICES, max_length=30)

    job = models.CharField(choices=JOB_CHOICES, max_length=30)
    first_name = models.CharField(_("first name"), max_length=30, blank=True)
    last_name = models.CharField(_("last name"), max_length=150, blank=True)
    is_admin = models.BooleanField(default=False)
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into this admin site."),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)
    create_feedback_email = models.EmailField(unique=True)

    objects = MyUserManager()

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email)

    def save(self, *args, **kwargs):
        if not self.create_feedback_email:
            self.create_feedback_email = self.generate_secret_email()
        super().save(*args, **kwargs)

    def generate_secret_email(self):
        alphabet = string.ascii_lowercase + string.digits
        secret = "".join(secrets.choice(alphabet) for i in range(10))
        return f"{secret}@mg.savio.io"

    def get_full_name(self):
        """
        Return the first_name plus the last_name, with a space in between.
        """
        full_name = "%s %s" % (self.first_name, self.last_name)
        return full_name.strip()

    def get_short_name(self):
        """Return the short name for the user."""
        return self.first_name

    def email_user(self, subject, message, from_email=None, **kwargs):
        """Send an email to this user."""
        send_mail(subject, message, from_email, [self.email], **kwargs)

    def get_email_domain(self):
        return self.email.split("@")[1]

    def send_verification_email(self):
        context = {
            "email": self.email,
            "domain": settings.EMAIL_DOMAIN,
            "site_name": "Savio.io",
            "user": self,
            "token": default_token_generator.make_token(self),
        }

        txt_email = loader.render_to_string(
            "chrome_extension_account_activate_email.txt", context
        )
        # html_email = loader.render_to_string(subject_template_name, context)

        send_mail(
            "Open this to activate your Savio account",
            txt_email,
            settings.DEFAULT_FROM_EMAIL,
            [self.email,],
            html_message=None,
        )

    def get_safe_role_choices(self):
        # Shouldn't be able to make users that have a "higher"
        # role then you
        if self.role == User.ROLE_OWNER:
            safe_roles = (("", "---------"),) + User.ROLE_CHOICES
        elif self.role == User.ROLE_ADMIN:
            safe_roles = (
                ("", "---------"),
                (User.ROLE_ADMIN, "Admin"),
                (User.ROLE_SUBMITTER, "Submitter"),
            )
        else:
            safe_roles = (("", "---------"),)
        return safe_roles

    # This was just hacked in for CE. Could be expanded to something more generally
    # useful.
    def get_permissions(self):
        if self.role == User.ROLE_SUBMITTER:
            can_create_feature_request = self.customer.submitters_can_create_features
        else:
            can_create_feature_request = True

        return {
            "can_create_feature_request": can_create_feature_request,
        }


class StatusEmailSettings(models.Model):
    NOTIFY_NEVER = "0_NEVER"
    NOTIFY_DAILY = "1_DAILY"

    NOTIFY_CHOICES = (
        (NOTIFY_NEVER, "Don't notify"),
        (NOTIFY_DAILY, "Daily"),
    )

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    notify = models.CharField(
        default=NOTIFY_NEVER, choices=NOTIFY_CHOICES, max_length=255
    )
    last_notified = models.DateTimeField(default=timezone.now, null=True, blank=True)
    first_email_sent = models.BooleanField(default=False)
    unsubscribe_token = models.UUIDField(default=uuid.uuid4, unique=True)


class FeatureRequestNotificationSettings(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    first_name_default = models.CharField(default="friend", blank=False, max_length=255)
    reply_to = models.EmailField(blank=True)
    bcc = models.TextField(blank=True)
    template = models.TextField(
        blank=True,
        default="""Hi {first_name},

Just a heads up - you asked for a feature, and we built it.

[Insert more about the Feature here]

Thanks for the request and keep 'em coming - we're always listening.

Cheers,

[Insert your name]""",
    )

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)


class FeedbackTriageSettings(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    skip_inbox_if_feature_request_set = models.BooleanField(default=False)

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)


class OnboardingTaskManager(models.Manager):
    def create_initial_tasks(self, customer):
        for task_type, task_name in OnboardingTask.TASK_TYPES:
            self.get_queryset().create(customer=customer, task_type=task_type)
        self.get_queryset().filter(
            customer=customer, task_type=OnboardingTask.TASK_CREATE_VAULT
        ).update(completed=True)

    def percent_complete(self, customer):
        total_tasks = self.get_queryset().filter(customer=customer).count()
        completed_tasks = (
            self.get_queryset().filter(customer=customer, completed=True).count()
        )
        if total_tasks > 0:
            val = round(completed_tasks / float(total_tasks), 2)
        else:
            val = 0
        return val


class OnboardingTask(models.Model):
    TASK_CREATE_VAULT = "TASK_CREATE_VAULT"
    TASK_CREATE_FEEDBACK = "TASK_CREATE_FEEDBACK"
    TASK_CREATE_FEATURE_REQUEST = "TASK_CREATE_FEATURE_REQUEST"
    TASK_TRIAGE_FEEDBACK = "TASK_TRIAGE_FEEDBACK"
    TASK_CONNECT_HELP_DESK = "TASK_CONNECT_HELP_DESK"
    TASK_SUBMIT_FEEDBACK_VIA_HELP_DESK = "TASK_SUBMIT_FEEDBACK_VIA_HELP_DESK"
    TASK_CREATE_FEEDBACK_CE = "TASK_CREATE_FEEDBACK_CE"
    TASK_VIEW_FEATURE_REQUEST_DETAILS = "TASK_VIEW_FEATURE_REQUEST_DETAILS"
    TASK_CLOSE_THE_LOOP = "TASK_CLOSE_THE_LOOP"

    TASK_TYPES = (
        (TASK_CREATE_VAULT, TASK_CREATE_VAULT),
        (TASK_CREATE_FEEDBACK, TASK_CREATE_FEEDBACK),
        (TASK_CREATE_FEATURE_REQUEST, TASK_CREATE_FEATURE_REQUEST),
        (TASK_TRIAGE_FEEDBACK, TASK_TRIAGE_FEEDBACK),
        (TASK_VIEW_FEATURE_REQUEST_DETAILS, TASK_VIEW_FEATURE_REQUEST_DETAILS),
        (TASK_CONNECT_HELP_DESK, TASK_CONNECT_HELP_DESK),
        (TASK_SUBMIT_FEEDBACK_VIA_HELP_DESK, TASK_SUBMIT_FEEDBACK_VIA_HELP_DESK),
        (TASK_CLOSE_THE_LOOP, TASK_CLOSE_THE_LOOP),
    )

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    task_type = models.CharField(choices=TASK_TYPES, blank=False, max_length=255)
    completed = models.BooleanField(default=False)
    skipped = models.BooleanField(default=False)

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    objects = OnboardingTaskManager()

    def get_open_in_new_tab(self):
        return self.task_type in (
            OnboardingTask.TASK_CREATE_FEEDBACK_CE,
            OnboardingTask.TASK_CLOSE_THE_LOOP,
        )

    def get_title(self):
        if self.task_type == OnboardingTask.TASK_CREATE_VAULT:
            title = "Create your feedback vault"
        elif self.task_type == OnboardingTask.TASK_CREATE_FEEDBACK:
            title = "Create your first piece of Feedback"
        elif self.task_type == OnboardingTask.TASK_CREATE_FEATURE_REQUEST:
            title = "Create your first Feature Request"
        elif self.task_type == OnboardingTask.TASK_TRIAGE_FEEDBACK:
            title = "Triage a piece of Feedback"
        elif self.task_type == OnboardingTask.TASK_CONNECT_HELP_DESK:
            title = "Connect Savio to your help desk"
        elif self.task_type == OnboardingTask.TASK_SUBMIT_FEEDBACK_VIA_HELP_DESK:
            title = "Send feedback from your help desk to Savio"
        elif self.task_type == OnboardingTask.TASK_CREATE_FEEDBACK_CE:
            title = "Submit feedback via Chrome Extension"
        elif self.task_type == OnboardingTask.TASK_VIEW_FEATURE_REQUEST_DETAILS:
            title = "View a feature request (and its feedback)"
        elif self.task_type == OnboardingTask.TASK_CLOSE_THE_LOOP:
            title = "Close the loop with feature requesters"
        else:
            raise Exception("Invalid onboarding task type")
        return title

    def get_url(self):
        onboarding_checklist_url = reverse_lazy("accounts-onboarding-checklist")
        if self.task_type == OnboardingTask.TASK_CREATE_VAULT:
            url = ""
        elif self.task_type == OnboardingTask.TASK_CREATE_FEEDBACK:
            url = reverse_lazy("feedback-inbox-create-item")
            url = f"{url}?return={onboarding_checklist_url}&onboarding=yes"
        elif self.task_type == OnboardingTask.TASK_CREATE_FEATURE_REQUEST:
            url = reverse_lazy("feature-request-create-item")
            url = f"{url}?return={onboarding_checklist_url}&onboarding=yes"
        elif self.task_type == OnboardingTask.TASK_TRIAGE_FEEDBACK:
            url = reverse_lazy("feedback-inbox-list", args=("active",))
            url = f"{url}?onboarding=yes"
        elif self.task_type == OnboardingTask.TASK_CONNECT_HELP_DESK:
            url = reverse_lazy("accounts-integration-settings-list")
            url = f"{url}?onboarding=yes"
        elif self.task_type == OnboardingTask.TASK_SUBMIT_FEEDBACK_VIA_HELP_DESK:
            url = ""
        elif self.task_type == OnboardingTask.TASK_CREATE_FEEDBACK_CE:
            url = reverse_lazy("download-chrome-extension")
        elif self.task_type == OnboardingTask.TASK_VIEW_FEATURE_REQUEST_DETAILS:
            url = reverse_lazy("feature-request-list")
            url = f"{url}?onboarding=yes"
        elif self.task_type == OnboardingTask.TASK_CLOSE_THE_LOOP:
            url = reverse_lazy("marketing-use-cases-close-loop")
        else:
            raise Exception("Invalid onboarding task type")
        return url
