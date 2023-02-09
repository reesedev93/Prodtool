from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, UsernameField
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage, EmailMultiAlternatives, mail_admins
from django.template import loader
from urllib.parse import quote
from stripe.error import CardError

from django.conf import settings
from appaccounts.models import AppCompany, AppUser
from internal_analytics import tracking
from sharedwidgets.widgets import SelectWidget

from .models import (
    Customer,
    FeatureRequestNotificationSettings,
    FeedbackTriageSettings,
    StatusEmailSettings,
    Subscription,
    User,
    Invitation,
    validate_domain,
)


class MyAuthenticationForm(AuthenticationForm):
    def clean_username(self):
        # Avoid confusion "Why can't I login with my.name@example.com"
        # when we've got My.Name@example.com stored in the db.
        # We also lower case email/username in forms to avoid
        # duplicates since we are lower casing on authentication.
        return self.cleaned_data["username"].lower()


class UserCreationForm(forms.ModelForm):
    """
    Modified version of the stock Djagno UserCreateForm that doesn't require
    password confirmation and hardcodes email as username field.
    """

    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput,
        help_text=password_validation.password_validators_help_text_html(),
    )

    class Meta:
        model = User
        fields = ("email",)
        field_classes = {"email": UsernameField}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self._meta.model.USERNAME_FIELD in self.fields:
            self.fields[self._meta.model.USERNAME_FIELD].widget.attrs.update(
                {"autofocus": True}
            )

    def _post_clean(self):
        super()._post_clean()
        # Validate the password after self.instance is updated with form data
        # by super().
        password = self.cleaned_data.get("password1")
        if password:
            try:
                password_validation.validate_password(password, self.instance)
            except forms.ValidationError as error:
                self.add_error("password1", error)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class JoinForm(UserCreationForm):
    JOB_CHOICES = [("", "")] + list(User.JOB_CHOICES)

    code = forms.CharField(widget=forms.HiddenInput(), required=False)
    plan = forms.CharField(widget=forms.HiddenInput(), required=False)
    company_name = forms.CharField(max_length=255, required=True)
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    job = forms.ChoiceField(
        choices=JOB_CHOICES, label="What team are you on?", required=True
    )

    def get_email_domain(self):
        return self.cleaned_data["email"].split("@")[-1]

    def clean_email(self):
        validate_domain(self.get_email_domain())
        return self.cleaned_data["email"].lower()

    def save(self, commit=True):
        user = super(JoinForm, self).save(commit=False)
        if commit:
            customer = Customer.objects.create(name=self.cleaned_data["company_name"])
            user.customer = customer
            user.role = User.ROLE_OWNER
            user.save()
            tracking.account_created(user)
            tracking.user_created(user, tracking.EVENT_SOURCE_WEB_APP)

            # Create an initial AppUser and AppCompany for the person that just
            # signed up so if they want to add themselves as the creater of some
            # feedback they'll be there to select.
            company = AppCompany.objects.create(
                customer=customer, name=self.cleaned_data["company_name"]
            )
            AppUser.objects.create(
                customer=customer,
                company=company,
                name=f"{self.cleaned_data['first_name']} {self.cleaned_data['last_name']}",
                email=self.cleaned_data["email"],
            )

            # The new account owner should automatically be signed up for
            # the daily status email. They can unsubscribe if they don't
            # like it.
            StatusEmailSettings.objects.create(
                customer=customer, user=user, notify=StatusEmailSettings.NOTIFY_DAILY
            )

        return user

    class Meta:
        model = User
        fields = (
            "company_name",
            "first_name",
            "last_name",
            "email",
            "job",
            "password1",
        )


class ChromeExtensionJoinForm(JoinForm):
    company_name = None

    def clean_email(self):
        validate_domain(self.get_email_domain())
        try:
            Customer.objects.get(whitelisted_domain=self.get_email_domain())
        except Customer.DoesNotExist:
            raise ValidationError(
                f"No account has {self.get_email_domain()} whitelisted.",
                code="not_whitelisted",
            )
        return self.cleaned_data["email"].lower()

    def save(self, commit=True):
        user = super(ChromeExtensionJoinForm, self).save(commit=False)
        if commit:
            customer = Customer.objects.get(whitelisted_domain=self.get_email_domain())
            user.customer = customer
            user.is_active = False
            user.role = User.ROLE_SUBMITTER
            user.save()
            tracking.user_created(user, tracking.EVENT_SOURCE_CE)
            user.send_verification_email()

            # Create an AppUser for this user so they can log feedback
            # against themselves.
            company = AppCompany.objects.guess_company(
                customer=customer, email=self.cleaned_data["email"]
            )
            AppUser.objects.get_or_create(
                customer=customer,
                email=self.cleaned_data["email"],
                defaults={
                    "name": f"{self.cleaned_data['first_name']} {self.cleaned_data['last_name']}",
                    "company": company,
                },
            )
        return user

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "job", "password1")


class UserCreateForm(JoinForm):
    company_name = None

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

        # Can't set via Meta!?
        self.fields["job"].label = "What team is this user on?"
        self.fields["role"].choices = self.request.user.get_safe_role_choices()

    def clean_role(self):
        if (
            self.request.user.role != User.ROLE_OWNER
            and self.cleaned_data["role"] == User.ROLE_OWNER
        ):
            raise ValidationError(
                "You can't create a user with that role.", code="invalid"
            )
        return self.cleaned_data["role"]

    def clean_email(self):
        return self.cleaned_data["email"].lower()

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            customer = self.request.user.customer
            user.customer = customer
            user.is_active = True
            user.save()
            tracking.user_created(user, tracking.EVENT_SOURCE_WEB_APP)

            # Create an AppUser for this user so they can log feedback
            # against themselves.
            company = AppCompany.objects.guess_company(
                customer=customer, email=self.cleaned_data["email"]
            )
            AppUser.objects.get_or_create(
                customer=customer,
                email=self.cleaned_data["email"],
                defaults={
                    "name": f"{self.cleaned_data['first_name']} {self.cleaned_data['last_name']}",
                    "company": company,
                },
            )

            # New Owners or Admins should automatically be signed up for
            # the daily status email. They can unsubscribe if they don't
            # like it.
            if user.role != User.ROLE_SUBMITTER:
                StatusEmailSettings.objects.create(
                    customer=customer,
                    user=user,
                    notify=StatusEmailSettings.NOTIFY_DAILY,
                )

        return user

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "role", "job", "password1")

        labels = {
            "job": "What team is this user on?",
        }


class UserUpdateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

        # Can't set via Meta!?
        self.fields["job"].label = "What team is this user on?"

    def clean_email(self):
        return self.cleaned_data["email"].lower()

    def clean_role(self):
        # If they aren't changing the role then we don't care. Allows an admin
        # to change non-role props for an owner.
        if self.instance.role != self.cleaned_data["role"]:
            if (
                self.request.user.role != User.ROLE_OWNER
                and self.cleaned_data["role"] == User.ROLE_OWNER
            ):
                raise ValidationError("You can't set that role.", code="invalid")

            downgrading_from_owner = (
                self.instance.role == User.ROLE_OWNER
                and self.cleaned_data["role"] != User.ROLE_OWNER
            )
            only_one_owner = (
                User.objects.filter(
                    customer=self.request.user.customer, role=User.ROLE_OWNER
                ).count()
                == 1
            )
            if downgrading_from_owner and only_one_owner:
                raise ValidationError(
                    "You must have at least one owner.", code="invalid"
                )

        return self.cleaned_data["role"]

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "role", "job")

        labels = {
            "job": "What team is this user on?",
        }

class InvitationCreateForm(forms.ModelForm):

    email = forms.CharField(widget=forms.HiddenInput(), required = False)
    
    field_order = ['email', 'emails', 'role']

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)
    
    def clean(self):
        cleaned_data = super(InvitationCreateForm, self).clean()
        emails = self.request.POST['emails']
        if(emails == ''):
            raise forms.ValidationError('Please input emails.')

        email_list = emails.replace(' ', '').split(',')

        existing_users = Invitation.objects.filter(customer=self.request.user.customer).count()
        max_users = self.request.user.customer.subscription.plan_users()

        if(max_users != 'Unlimited'):
            if(int(max_users) - 1 < existing_users + len(email_list)):
                raise forms.ValidationError('You can not invite users anymore.')

        for email in email_list:
            try:
                validate_email(email)
            except ValidationError:
                raise forms.ValidationError("Your input contains an invalid email.")

            if(Invitation.objects.filter(email=email).count() > 0):
                raise forms.ValidationError("Your input contains an existing email.")
        return cleaned_data

    def clean_email(self):
        return self.cleaned_data["email"].lower()

    def save(self, commit=True):
        invite = super().save(commit=False)
        if commit:
            customer = self.request.user.customer
            invite.customer = customer
            role = self.request.POST['role']
            emails = self.request.POST['emails'].split(',')
            for email in emails:
                invite.email = email
                Invitation.objects.create(email=email, role=role, customer=customer)
                self.send_invitation_email(email)

        return invite
    
    def send_invitation_email(self, email):
        subject = f"{self.request.user.get_full_name()} has invited you to join Savio"
        reply_to = [self.request.user.email]

        from_email = (
            f"{self.request.user.get_full_name()} via Savio <email@mg.savio.io>"
        )

        invitation = Invitation.objects.get(email=email)
        url = settings.APP_URL + '/app/accounts/' + str(invitation.id) + '/sign-up'
        
        html_body = loader.render_to_string(
            "email/invitation_email.html",
            {
                "customer": quote(self.request.user.customer.name),
                "invitation_url": url
            },
        )

        txt_email = loader.render_to_string(
            "email/invitation_email.txt", {"body": 'You have been invited to Savio',},
        )

        msg = EmailMultiAlternatives(
            subject,
            txt_email,
            from_email,
            [email],
        )

        msg.attach_alternative(html_body, "text/html")
        msg.send()

    class Meta:
        model = Invitation
        fields = ("email", "role")


class WhitelistForm(forms.ModelForm):
    whitelist_domain = forms.BooleanField(
        initial=True,
        required=False,
        label="Allow people to sign up with their verified",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        model = Customer
        fields = [
            "whitelisted_domain",
        ]

        widgets = {
            "whitelisted_domain": forms.HiddenInput(),
        }


class WhitelistSettingsForm(forms.ModelForm):
    def clean_whitelist_domain(self):
        validate_domain(self.cleaned_data["whitelisted_domain"])
        return self.cleaned_data["whitelisted_domain"]

    class Meta:
        model = Customer
        fields = [
            "whitelisted_domain",
        ]


class SubmittersCanCreateFeaturesSettingsForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "submitters_can_create_features",
        ]


class SubscriptionEditForm(forms.ModelForm):
    stripe_token = forms.CharField(
        max_length=255, required=True, widget=forms.HiddenInput()
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)
        self.fields["plan"].choices = Subscription.FEATURE_TIERED_PLAN_CHOICES

        if self.request.user.customer.num_users() > 3:
            self.fields["plan"].widget.disabled_choices = [
                Subscription.PLAN_1_USER_FREE,
                Subscription.PLAN_3_USERS_25,
            ]
            plan_help_text = "Can't downgrade? <a href='mailto:support@savio.io?subject=Downgrade Plan'>Email support for help.</a>"
        elif self.request.user.customer.num_users() > 1:
            self.fields["plan"].widget.disabled_choices = [
                Subscription.PLAN_1_USER_FREE
            ]
            plan_help_text = "Can't downgrade? <a href='mailto:support@savio.io?subject=Downgrade Plan'>Email support for help.</a>"
        else:
            plan_help_text = ""

        self.fields[
            "plan"
        ].help_text = f"<a href='{reverse_lazy('marketing-pricing')}' target='_blank'>Compare plans here</a>. {plan_help_text}"

        # If they're not feature tiered and they don't have a cancelled plan, hide plans dropdown
        if (
            not self.instance.is_feature_tiered()
        ) and self.instance.has_non_canceled_stripe_subscription():
            self.fields["plan"].widget = forms.HiddenInput()

        if not self.request.GET.get("add_card", None):
            del self.fields["stripe_token"]

    def clean(self):
        # This code should really be in form.save() but the only way
        # to validate the token is to actually try and add it to the
        # customer so we do that here so we can report a nice erorr
        # if the card doesn't work. Sure would be nice if StripeJS
        # createToken never returned a token unless the token was
        # guaranteed to be valid!
        # See:
        # https://stackoverflow.com/questions/49637043/is-it-possible-to-verify-cvc-zip-code-and-address-1-on-stripe-createtoken
        cleaned_data = super().clean()

        # KM: We won't POST stripe_token if we haven't shown the add cc form
        # (which we show when add_card=1
        if self.request.GET.get("add_card", None) == "1":
            try:
                self.instance.add_tokenized_card(self.cleaned_data["stripe_token"])
            except CardError as e:
                raise ValidationError(e.user_message)

        return cleaned_data

    def save(self, commit=True):
        try:
            sub_in_db = Subscription.objects.filter(
                customer=self.instance.customer
            ).first()

            # If we're saving the subscription edit form, and the sub in db doesn't point to
            # an active Stripe sub (which is what .inactive() checks for),
            # the customer is reactivating their sub. We will need to create a new sub
            # in Stripe AND our db (and delete our old db sub).  This is because when a
            # sub is cancelled in Stripe, we can't update it so the db stripe_id doesn't
            # point to anything in Stripe anymore.
            if sub_in_db.inactive():
                sub_in_db.delete()
                self.instance.create_new_stripe_subscription(
                    self.cleaned_data.get("plan")
                )
            else:
                # Sub in db is active.  Is what's POSTed isn't same as in our db,
                # we've changed our sub and need to update it.
                if sub_in_db.plan != self.instance.plan:
                    self.instance.modify_stripe_subscription(
                        self.cleaned_data.get("plan")
                    )

            # Turn off whitelist if customer not on unlimited plan
            if self.instance.plan != Subscription.PLAN_UNLIMITED_USERS_49:
                try:
                    customer = Customer.objects.filter(
                        pk=self.instance.customer.pk
                    ).first()
                    customer.turn_off_whitelist()

                except Customer.DoesNotExist:
                    pass

        except Subscription.DoesNotExist:
            # No sub in db - we're adding a new sub
            self.instance.create_new_stripe_subscription(self.cleaned_data.get("plan"))

    class Meta:
        model = Subscription
        fields = ["customer", "stripe_token", "plan"]

        widgets = {"customer": forms.HiddenInput(), "plan": SelectWidget}


class StatusEmailSettingsForm(forms.ModelForm):
    class Meta:
        model = StatusEmailSettings
        fields = [
            "notify",
        ]


class FeedbackTriageSettingsForm(forms.ModelForm):
    class Meta:
        model = FeedbackTriageSettings
        fields = [
            "skip_inbox_if_feature_request_set",
        ]


class FeatureRequestNotificationSettingsForm(forms.ModelForm):
    class Meta:
        model = FeatureRequestNotificationSettings
        fields = ["first_name_default", "reply_to", "bcc", "template"]

        labels = {
            "first_name_default": "Default value for first name",
            "template": "Email template",
        }

        help_texts = {
            "first_name_default": "We'll substitute this for the {first_name} variable if you email someone with an unknown name.",
            "reply_to": "Replies to feature request emails will be sent here. You might set this to support@your_domain.com.",
            "bcc": "One per line. Savio will bcc these addresses on feature request emails to customers. Useful to track customer emails in your CRM.",
            "template": "The default body for feature request emails.",
        }
