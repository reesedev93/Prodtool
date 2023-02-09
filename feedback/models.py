import uuid
from django.db import models
from django.db.models import Count, Sum, FloatField
from django.db.models.functions import Cast
from django.conf import settings
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.urls import reverse
from django.utils import timezone
from datetime import datetime
from common.utils import get_class, remove_markdown
from common.model_mixins import InitialsMixin
from accounts.models import Customer, User, OnboardingTask
from appaccounts.models import AppUser, FilterableAttribute

def generate_webhook_secret():
    return str(uuid.uuid4())

class FeedbackImporter(models.Model):
    name = models.CharField(max_length=255)
    module = models.CharField(max_length=255)

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    def __str__(self):
        return self.name

    def icon_filename(self):
        if self.name == "Intercom":
            return "images/intercom.png"
        elif self.name == "Segment":
            return "images/segment.png"
        else:
            raise Exception(f"No feedback importer icon for {self.name}")

class CustomerFeedbackImporterSettings(models.Model):
    importer = models.ForeignKey(FeedbackImporter, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)

    account_id = models.CharField(max_length=255, blank=True)
    api_key = models.CharField(max_length=255, blank=True)
    refresh_token = models.CharField(max_length=255, blank=True)
    webhook_secret = models.CharField(max_length=255, default=generate_webhook_secret, unique=True)
    last_requested_at = models.DateTimeField(null=True, blank=True)
    feedback_tag_name = models.CharField(max_length=255, blank=True)

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        unique_together = (("importer", "customer", "account_id"),)

    def handle_webhook(self, json, secret=None, event=None):
        self.get_importer().handle_webhook(json, secret=secret, event=event)

    def do_import(self, all_data=False):
        self.get_importer().execute(all_data=all_data)

    def get_importer(self):
        importer_class = get_class(self.importer.module)
        return importer_class(self)

    def save_refreshed_tokens(self, new_access_token, new_refresh_token):
        self.api_key = new_access_token
        self.refresh_token = new_refresh_token
        self.save()

class Theme(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)

    title = models.CharField(max_length=1024)
    color = models.CharField(max_length=30, blank=True)
    import_token = models.CharField(blank=True, max_length=36, help_text="Used to keep track of all of the items created in a single admin import for easy deletion in case of disaster.")

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        unique_together = [['customer', 'title']]
        ordering = ['title']

    def __str__(self):
        return f"{self.title}"

class FeatureRequestQuerySet(models.QuerySet):
    # Available on both Manager and QuerySet.
    def with_counts(self, customer):
        qs = self.annotate(
            total_feedback=Count('feedback'),
            total_users=Count('feedback__user', distinct=True),
            total_companies=Count('feedback__user__company', distinct=True))
        lookup = FilterableAttribute.objects.get_mrr_lookup(customer)
        if lookup:
            lookup_base, attribute_name = lookup
            lookup_base = f'feedback__{lookup_base}'
            qs = qs.annotate(total_mrr=Sum(Cast(KeyTextTransform(attribute_name, lookup_base), FloatField())))
        else:
            # This little shit sandwitch in necessary to make Django's ORM
            # happy when we don't have an FA setup for MRR. We are just
            # generated a sum that is NULL. If we do something simple like
            # qs.annotate(total_mrr=Value(0.0, FloatField()))
            # headers.get_order_by_expression() doens't like it. Perhaps
            # there is a better way but this works.
            qs = qs.annotate(total_mrr=Sum(Cast(None, FloatField())))
        return qs

class FeatureRequest(InitialsMixin, models.Model):
    UNTRIAGED = 'UNTRIAGED'
    UNDER_CONSIDERATION = 'UNDER_CONSIDERATION'
    PLANNED = 'PLANNED'
    IN_PROGRESS = 'IN_PROGRESS'
    SHIPPED = 'SHIPPED'
    CUSTOMER_NOTIFIED = 'CUSTOMER_NOTIFIED'
    WONT_DO = 'WONT_DO'

    STATE_KEYS = (
        UNTRIAGED,
        UNDER_CONSIDERATION,
        PLANNED,
        IN_PROGRESS,
        SHIPPED,
        WONT_DO,
    )

    ACTIVE_STATE_KEYS = (
        UNTRIAGED,
        UNDER_CONSIDERATION,
        PLANNED,
        IN_PROGRESS,
    )

    STATE_CHOICES = (
        (UNTRIAGED, 'Untriaged'),
        (UNDER_CONSIDERATION, 'Under Consideration'),
        (PLANNED, 'Planned'),
        (IN_PROGRESS, 'In Progress'),
        (SHIPPED, 'Shipped'),
        (CUSTOMER_NOTIFIED, 'Customer Notified'),
        (WONT_DO, "Won't do"),
    )

    HIGH = '3_HIGH'
    MEDIUM = '2_MEDIUM'
    LOW = '1_LOW'

    PRIORITY_KEYS = (
        LOW,
        MEDIUM,
        HIGH,
    )
    PRIORITY_CHOICES = (
        (LOW, 'Low'),
        (MEDIUM, 'Medium'),
        (HIGH, 'High'),
    )

    EFFORT_KEYS = (
        LOW,
        MEDIUM,
        HIGH,
    )
    EFFORT_CHOICES = (
        (LOW, 'Low'),
        (MEDIUM, 'Medium'),
        (HIGH, 'High'),
    )

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)

    title = models.CharField(max_length=1024)
    description = models.TextField(blank=True)
    state = models.CharField(choices=STATE_CHOICES, default='UNTRIAGED', max_length=30)
    themes = models.ManyToManyField(Theme, blank=True)
    priority = models.CharField(choices=PRIORITY_CHOICES, blank=True, max_length=30)
    effort = models.CharField(choices=EFFORT_CHOICES, blank=True, max_length=30)
    import_token = models.CharField(blank=True, max_length=36, help_text="Used to keep track of all of the items created in a single admin import for easy deletion in case of disaster.")

    shipped_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    objects = FeatureRequestQuerySet().as_manager()

    def __str__(self):
        return f"{self.title}"

    def set_shipped_at(self):
        # If this FR was just set to shipped, set shipped_at
        if "state" in self.changed_fields() and self.state == FeatureRequest.SHIPPED:
            self.shipped_at = timezone.now()

        # If this FR was shipped, but now isn't, null out shipped_at
        if "state" in self.changed_fields() and self.state != FeatureRequest.SHIPPED:
            self.shipped_at = None

    def save(self, *args, **kwargs):
        self.set_shipped_at()

        if not self.id:
            OnboardingTask.objects.filter(customer=self.customer, task_type=OnboardingTask.TASK_CREATE_FEATURE_REQUEST).update(completed=True, updated=timezone.now())
        super(FeatureRequest, self).save(*args, **kwargs)


class FeedbackManager(models.Manager):
    def unsnooze_feedback(self):
        return Feedback.objects.filter(snooze_till__lte=timezone.now()).update(
            snooze_till=None, state=Feedback.ACTIVE)

class Feedback(models.Model):
    ACTIVE = 'ACTIVE'
    PENDING = 'PENDING'
    ARCHIVED = 'ARCHIVED'

    STATE_KEYS = (
        ACTIVE,
        PENDING,
        ARCHIVED,
    )
    STATE_CHOICES = (
        (ACTIVE, 'Active'),
        (PENDING, 'Pending'),
        (ARCHIVED, 'Archived'),
    )

    EXISTING = 'ACTIVE'
    CHURNED = 'CHURNED'
    LOST_DEAL = 'LOST DEAL'
    INTERNAL = 'INTERNAL'
    PROSPECT = 'PROSPECT'
    OTHER = 'OTHER'

    TYPE_KEYS = (
        EXISTING,
        CHURNED,
        LOST_DEAL,
        INTERNAL,
        PROSPECT,
        OTHER,
    )
    TYPE_CHOICES = (
        (EXISTING, 'Active customer'),
        (CHURNED, 'Churned customer'),
        (INTERNAL, 'Internal user'),
        (LOST_DEAL, 'Lost deal'),
        (PROSPECT, 'Prospect'),
        (OTHER, 'Other'),
    )

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    user = models.ForeignKey(AppUser, null=True, blank=False, on_delete=models.SET_NULL)
    feature_request = models.ForeignKey(FeatureRequest, null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    title = models.CharField(max_length=1024, blank=True)
    problem = models.TextField()
    solution = models.TextField(blank=True)
    themes = models.ManyToManyField(Theme, blank=True)
    raw_content = models.TextField(blank=True) # Just for API based importing. Might delete.
    source = models.ForeignKey(FeedbackImporter, null=True, blank=True, on_delete=models.SET_NULL)
    source_url = models.URLField(default="", blank=True, max_length=2000)
    source_username = models.CharField(max_length=1024, blank=True)
    state = models.CharField(choices=STATE_CHOICES, default='ACTIVE', max_length=30)
    feedback_type = models.CharField(blank=False, choices=TYPE_CHOICES, max_length=30)
    snooze_till = models.DateTimeField(null=True, blank=True)
    import_token = models.CharField(blank=True, max_length=36, help_text="Used to keep track of all of the items created in a single admin import for easy deletion in case of disaster.")

    notified_by = models.ForeignKey(User, null=True, blank=True, related_name='notified_users', on_delete=models.SET_NULL)
    notified_at = models.DateTimeField(null=True, blank=True)

    source_created = models.DateTimeField(null=True, blank=True)
    source_updated = models.DateTimeField(null=True, blank=True)

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    objects = FeedbackManager()

    def save(self, *args, **kwargs):
        override_auto_triage = kwargs.pop('override_auto_triage', False)

        if self.state != Feedback.PENDING: # If we aren't pending clear snooze_til
            self.snooze_till = None

        # If this is a new piece of feedback and the feedback_type isn't already
        # set then set it to the user configured default.
        if not self.id and not self.feedback_type:
            self.feedback_type = self.get_default_feedback_type()

        # Auto-triage if required
        if not self.id and not override_auto_triage and self.skip_inbox():
            self.state = Feedback.ARCHIVED

        # Checkoff onboarding task
        if not self.id:
            OnboardingTask.objects.filter(customer=self.customer, task_type=OnboardingTask.TASK_CREATE_FEEDBACK).update(completed=True, updated=timezone.now())
        super(Feedback, self).save(*args, **kwargs)

    def skip_inbox(self):
        triage_settings = self.customer.feedbacktriagesettings_set.first()
        if triage_settings:
            skip = triage_settings.skip_inbox_if_feature_request_set and self.feature_request
        else:
            skip = False
        return skip

    def get_default_feedback_type(self):
        # Returns the user configured default feedback_type
        default_choice = ""
        if self.user:
            try:
                rule = FeedbackFromRule.objects.get(customer=self.customer)
                if rule.filterable_attribute:
                    if rule.filterable_attribute.related_object_type == FilterableAttribute.OBJECT_TYPE_APPUSER:
                        value = self.user.filterable_attributes.get(rule.filterable_attribute.name, "")
                        if rule.get_coerced_trigger_value() == value:
                            default_choice = rule.default_feedback_type
                    elif rule.filterable_attribute.related_object_type == FilterableAttribute.OBJECT_TYPE_APPCOMPANY and self.user.company:
                        value = self.user.company.filterable_attributes.get(rule.filterable_attribute.name, "")
                        if rule.get_coerced_trigger_value() == value:
                            default_choice = rule.default_feedback_type
            except (FeedbackFromRule.DoesNotExist, ValueError):
                pass
        return default_choice

    def has_structured_content(self):
        return self.title or self.problem or self.solution

    def is_pending(self):
        return self.state == Feedback.PENDING

    def is_active(self):
        return self.state == Feedback.ACTIVE

    def __repr__(self):
        return f"{self.title}"

    # Problem can be markdown and displaying markdown is lists and messages
    # looks like ass. Use this method to get nice snippet for display.
    def get_problem_snippet(self, snippet_length=100, join_char="\n"):
        # Sometimes we are forced to turn converstation threads into
        # one big lump. When we do that we prefix the individual convos
        # like this:
        # From: Bob Smith
        # Date: 2019-01-01
        # If we've done that we need to whack that
        lines = self.problem.split('\n')
        try:
            if '**From**:' in lines[0] and '**Date**:' in lines[1]:
                lines = lines[2:]
        except IndexError:
            pass
        problem_markdown = "\n".join(lines)
        markdown_less = remove_markdown(problem_markdown, length=snippet_length, join_char=join_char)
        if markdown_less:
            snippet = markdown_less
        else:
            # Even though we require a problem it's possible one won't be set.
            # One case we have this is when the user tags a message in Intercom
            # that only has an image in it and no text.
            snippet = "N/A"
        return snippet

    def get_absolute_url(self):
        return reverse('feedback-item', args=[str(self.id)])

    def get_friendly_creator_name(self):
        if self.created_by:
          s = f"{self.created_by.first_name} {self.created_by.last_name}"
        elif self.source_username:
          s = f"@{self.source_username}"
        else:
          s = ""

        return s

class FeedbackFromRule(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    filterable_attribute = models.ForeignKey(FilterableAttribute, null=True, on_delete=models.CASCADE)
    default_feedback_type = models.CharField(blank=False, choices=Feedback.TYPE_CHOICES, max_length=30)
    attribute_value_trigger = models.CharField(max_length=255, blank=True)

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    def get_coerced_trigger_value(self):
        return self.filterable_attribute.get_coercion_fuction(self.attribute_value_trigger)

class FeedbackTemplate(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    template = models.TextField(blank=True)

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)
