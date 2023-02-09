from django.contrib.postgres.fields import JSONField
from django.contrib.postgres.indexes import GinIndex
from django.core.cache import cache
from django.db import IntegrityError, models

from accounts.models import Customer

# NB: Dealing with uniqueness i.e. create vs. update for data sync cases
# The scenario here look like this:
# 1. Customer sends their User and Company data to Intercom
# 2. Intercom has some rules to understand whether it should update or create a new object
# See here:
# https://developers.intercom.com/intercom-api-reference/reference#create-or-update-user
# 3. We import the data into our system
# Basically: CustomerUser -> IntercomUser -> OurAppUser
# Each of the above have their own primary key.
#
# Intercom allows the customer to pass along their primary key field.
# Intercom stores those in User.user_id and Company.company_id.
#
# When importing their User and Company we use Intercoms ID field (e.g. user.id)
# which we map to our 'remote_id' field. We also store the ID field the customer
# has passed along and stored in user_id and company_id but we aren't actually
# using it for anything currently. We store that data in the `internal_id`
# field.
#
# The reasoning for the above is that Intercom is dealing with uniqueness handling
# on their end so it makes the most sense to rely on their ID field for look ups
# on our end i.e. `remote_id`.
#
# At some point we might want to revist this when we add more integration partners
# as there are likely some edge caeses hiding in here.


class FilterableAttributeManager(models.Manager):
    def get_mrr_lookup(self, customer):
        fa = self.get_mrr_attribute(customer)
        if fa and fa.related_object_type == FilterableAttribute.OBJECT_TYPE_APPCOMPANY:
            lookup = ("user__company__filterable_attributes", fa.name)
        elif fa and fa.related_object_type == FilterableAttribute.OBJECT_TYPE_APPUSER:
            lookup = ("user__filterable_attributes", fa.name)
        else:
            lookup = None
        return lookup

    def get_plan_display_name(self, customer):
        fa = self.get_plan_attribute(customer)
        if fa:
            display_name = fa.friendly_name
        else:
            display_name = "Plan"
        return display_name

    def get_mrr_display_name(self, customer):
        fa = self.get_mrr_attribute(customer)
        if fa:
            display_name = fa.friendly_name
        else:
            display_name = "MRR"
        return display_name

    def get_mrr_attribute(self, customer):
        try:
            fa = self.get_queryset().filter(customer=customer).get(is_mrr=True)
        except FilterableAttribute.DoesNotExist:
            fa = None
        return fa

    def get_plan_attribute(self, customer):
        try:
            fa = self.get_queryset().filter(customer=customer).get(is_plan=True)
        except FilterableAttribute.DoesNotExist:
            fa = None
        return fa

    def get_company_display_attributes(self, customer):
        return FilterableAttribute.objects.filter(
            customer=customer,
            show_in_badge=True,
            related_object_type=FilterableAttribute.OBJECT_TYPE_APPCOMPANY,
        ).order_by("friendly_name")

    def get_user_display_attributes(self, customer):
        return FilterableAttribute.objects.filter(
            customer=customer,
            show_in_badge=True,
            related_object_type=FilterableAttribute.OBJECT_TYPE_APPUSER,
        ).order_by("friendly_name")


class FilterableAttribute(models.Model):
    OBJECT_TYPE_APPUSER = "APPUSER"
    OBJECT_TYPE_APPCOMPANY = "APPCOMPANY"

    OBJECT_TYPE_KEYS = (
        OBJECT_TYPE_APPUSER,
        OBJECT_TYPE_APPCOMPANY,
    )

    OBJECT_TYPE_CHOICES = (
        (OBJECT_TYPE_APPUSER, "Person"),
        (OBJECT_TYPE_APPCOMPANY, "Company"),
    )

    ATTRIBUTE_TYPE_STR = "str"
    ATTRIBUTE_TYPE_BOOL = "bool"
    ATTRIBUTE_TYPE_FLOAT = "float"
    ATTRIBUTE_TYPE_INT = "int"

    ATTRIBUTE_TYPE_KEYS = (
        ATTRIBUTE_TYPE_STR,
        ATTRIBUTE_TYPE_BOOL,
        ATTRIBUTE_TYPE_FLOAT,
        ATTRIBUTE_TYPE_INT,
    )

    ATTRIBUTE_TYPE_CHOICES = (
        (ATTRIBUTE_TYPE_STR, "String"),
        (ATTRIBUTE_TYPE_BOOL, "True/False"),
        (ATTRIBUTE_TYPE_FLOAT, "Float"),
        (ATTRIBUTE_TYPE_INT, "Integer"),
    )

    WIDGET_TYPE_SELECT = "Select"
    WIDGET_TYPE_GROUPED_SELECT = "GroupedSelect"

    WIDGET_TYPE_KEYS = (
        WIDGET_TYPE_SELECT,
        WIDGET_TYPE_GROUPED_SELECT,
    )

    # BUGBUG: We don't really need WIDGET_TYPE_GROUPED_SELECT
    # any more now that we do numeric filters with the multi-widget
    # we should get rid of it, mirgrate the data and remove the
    # optoin from the UI. It doesn't hurt anything but it adds
    # needless complexity for the user and to our codebase.
    WIDGET_TYPE_CHOICES = (
        (WIDGET_TYPE_SELECT, "Select"),
        (WIDGET_TYPE_GROUPED_SELECT, "Grouped Select"),
    )

    @classmethod
    def get_filtered_attribute_type_from_value(cls, value):
        if type(value) == str:
            type_name = "str"
        elif type(value) == bool:
            type_name = "bool"
        elif type(value) == float:
            type_name = "float"
        elif type(value) == int:
            type_name = "int"
        else:
            raise Exception(f"Invalid type: {type(value)}.")
        return type_name

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    source = models.ForeignKey("feedback.FeedbackImporter", on_delete=models.CASCADE)

    name = models.CharField(max_length=256)
    friendly_name = models.CharField(max_length=256)
    related_object_type = models.CharField(choices=OBJECT_TYPE_CHOICES, max_length=256)
    attribute_type = models.CharField(choices=ATTRIBUTE_TYPE_CHOICES, max_length=256)
    widget = models.CharField(choices=WIDGET_TYPE_CHOICES, max_length=256)
    is_custom = models.BooleanField()

    show_in_filters = models.BooleanField(default=False)
    is_mrr = models.BooleanField(default=False)
    is_plan = models.BooleanField(default=False)
    show_in_badge = models.BooleanField(default=False)

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    objects = FilterableAttributeManager()

    def get_coercion_fuction(self, value):
        if self.attribute_type == FilterableAttribute.ATTRIBUTE_TYPE_STR:
            return str(value)
        elif self.attribute_type == FilterableAttribute.ATTRIBUTE_TYPE_BOOL:
            if value in ("True", "true", "TRUE", "T"):
                return True
            elif value in ("False", "false", "FALSE", "F"):
                return False
            else:
                return bool(value)
        elif self.attribute_type == FilterableAttribute.ATTRIBUTE_TYPE_FLOAT:
            return float(value)
        elif self.attribute_type == FilterableAttribute.ATTRIBUTE_TYPE_INT:
            return int(value)
        else:
            raise Exception(f"Invalid type: {self.attribute_type}.")

    def get_cache_key(self):
        return f"filterable_attribute_choices_{self.id}"

    def refresh_cache(self):
        return cache.set(self.get_cache_key(), None)

    def get_choices(self):
        cached_value = cache.get(self.get_cache_key())

        if cached_value:
            return cached_value

        if self.related_object_type == FilterableAttribute.OBJECT_TYPE_APPCOMPANY:
            qs = AppCompany.objects.filter(customer=self.customer)
        elif self.related_object_type == FilterableAttribute.OBJECT_TYPE_APPUSER:
            qs = AppUser.objects.filter(customer=self.customer)
        else:
            raise Exception(f"Invalid related_object_type: {self.related_object_type}")

        if self.attribute_type == FilterableAttribute.ATTRIBUTE_TYPE_BOOL:
            attribute_values = ("True", "False")
        else:
            kwargs = dict()
            kwargs[f"filterable_attributes__{self.name}__isnull"] = False
            attribute_values = (
                qs.filter(**kwargs)
                .values_list(f"filterable_attributes__{self.name}", flat=True)
                .distinct()
            )

        if self.widget == FilterableAttribute.WIDGET_TYPE_SELECT:
            attribute_choices = [(None, "All")] + [
                (value, value) for value in attribute_values
            ]
        elif self.widget == FilterableAttribute.WIDGET_TYPE_GROUPED_SELECT:
            # BUGBUG we should just kill WIDGET_TYPE_GROUPED_SELECT
            attribute_choices = [
                (None, "All"),
            ]
        else:
            raise Exception(f"Invalid widget: {self.widget}")

        cache.set(self.get_cache_key(), attribute_choices, 24 * 60 * 60)
        return attribute_choices

    def __str__(self):
        return f"{self.name}"


class AppCompanyManager(models.Manager):
    def guess_company(self, customer, email):
        company = None
        try:
            # Just the domain if they've passed the whole thing
            domain = email.split("@")[1]
            domain = f"@{domain}"
            candidate_company_ids = (
                AppUser.objects.filter(
                    customer=customer, email__icontains=domain, company__isnull=False
                )
                .values_list("company_id", flat=True)
                .distinct()
            )
            if candidate_company_ids.count() == 1:
                # All the AppUsers with a company with that email domain
                # have the same company so it's safe to auto set the company
                company = AppCompany.objects.get(
                    customer=customer, id=candidate_company_ids[0]
                )
        except IndexError:
            pass
        return company


class AppCompany(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)

    remote_id = models.CharField(max_length=255, null=True, blank=True)  # See user
    internal_id = models.CharField(max_length=255, null=True, blank=True)  # See user
    name = models.CharField(max_length=255)
    plan = models.CharField(max_length=255, default="", blank=True)
    monthly_spend = models.FloatField(null=True, blank=True)
    filterable_attributes = JSONField(default=dict)
    import_token = models.CharField(
        blank=True,
        max_length=36,
        help_text="Used to keep track of all of the items created in a single admin import for easy deletion in case of disaster.",
    )

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    objects = AppCompanyManager()

    class Meta:
        unique_together = (
            ("customer", "remote_id"),
            ("customer", "internal_id"),
        )

        indexes = [
            GinIndex(fields=["filterable_attributes"], name="appcompany_fa_gin",),
        ]

    def __str__(self):
        return self.name


class AppUserManager(models.Manager):
    def get_best_match_user(self, customer, email, remote_id, internal_id):
        users = self.get_queryset().filter(customer=customer)
        found = False
        user = None
        if remote_id:
            try:
                user = users.get(remote_id=remote_id)
            except AppUser.DoesNotExist:
                pass

        if not found and internal_id:
            try:
                user = users.get(internal_id=internal_id)
            except AppUser.DoesNotExist:
                pass

        if not found and email:
            try:
                user = users.get(email=email)
            except AppUser.DoesNotExist:
                pass
        return user

    def update_or_create_by_email_or_remote_id(
        self, customer, email, remote_id, defaults=dict()
    ):
        # First try and update the AppUser with the matching email otherwise try and
        # update by the remote_id. The main case we care about is if the user manually
        # made an app user with a given email and then later and integration tries and
        # makes it.
        #
        # This code doesn't handle cases where the user manually created an AppUser with a
        # given email, a remote gets created w/o an email and then the email gets added
        # later. That case requires a merge and it's not clear that we want to be auto-merging.
        # We aren't swallowing the error so the logs will start complaining if that happens.
        # We also have some weirdness with remote_id and internal_id. Right now Segment
        # uses internal_id and Intercom uses remote_id. It's not clear that's a great idea.
        assert remote_id
        if email:
            try:
                defaults["remote_id"] = remote_id
                return self.get_queryset().update_or_create(
                    customer=customer, email=email, defaults=defaults,
                )
            except IntegrityError:
                pass

        defaults["email"] = email or None
        return self.get_queryset().update_or_create(
            customer=customer, remote_id=remote_id, defaults=defaults,
        )

    def update_or_create_by_email_or_internal_id(
        self, customer, email, internal_id, defaults=dict()
    ):
        # See update_or_create_by_email_or_remote_id
        assert internal_id
        if email:
            try:
                defaults["internal_id"] = internal_id
                return self.get_queryset().update_or_create(
                    customer=customer, email=email, defaults=defaults,
                )
            except IntegrityError:
                pass

        defaults["email"] = email or None
        return self.get_queryset().update_or_create(
            customer=customer, internal_id=internal_id, defaults=defaults,
        )

    def merge(self, to_keep, to_delete):
        assert to_keep.id != to_delete.id
        assert to_keep.customer == to_delete.customer

        attr_names = (
            "email",
            "name",
            "remote_id",
            "internal_id",
            "company",
            "phone",
        )

        for attr_name in attr_names:
            new_val = getattr(to_keep, attr_name) or getattr(to_delete, attr_name)
            setattr(to_keep, attr_name, new_val)

        to_delete.feedback_set.update(user=to_keep)
        company = to_delete.company
        to_delete.delete()
        to_keep.save()
        if company and not company.appuser_set.all().exists():
            company.delete()


class AppUser(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    company = models.ForeignKey(
        AppCompany, null=True, blank=True, on_delete=models.CASCADE
    )

    remote_id = models.CharField(
        max_length=255, null=True, blank=True
    )  # The id on the integrated system e.g. Intercom
    internal_id = models.CharField(
        max_length=255, null=True, blank=True
    )  # The id our customer uses internally
    name = models.CharField(max_length=255, blank=False)
    email = models.EmailField(
        blank=True, null=True
    )  # AppUsers via importers might not have an email
    phone = models.CharField(max_length=30, blank=True)
    filterable_attributes = JSONField(default=dict)
    import_token = models.CharField(
        blank=True,
        max_length=36,
        help_text="Used to keep track of all of the items created in a single admin import for easy deletion in case of disaster.",
    )

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    objects = AppUserManager()

    class Meta:
        unique_together = (
            ("customer", "remote_id"),
            ("customer", "internal_id"),
            ("customer", "email"),
        )

        # NB: 0017_add_indexes_to_appuser_email_and_name.py adds GIN trigram UPPER
        # indexes to email and name using Raw SQL. There isn't a built in Index class
        # for that in Django 2.1 and I don't want to take the time to write one.
        indexes = [
            GinIndex(fields=["filterable_attributes"], name="appuser_fa_gin",),
        ]

    def get_attribute_value_from_company_or_user(self, fa):
        if fa is None:
            value = None
        elif fa.related_object_type == FilterableAttribute.OBJECT_TYPE_APPCOMPANY:
            if self.company:
                value = self.company.filterable_attributes.get(fa.name, None)
            else:
                value = None
        elif fa.related_object_type == FilterableAttribute.OBJECT_TYPE_APPUSER:
            value = self.filterable_attributes.get(fa.name, None)
        else:
            raise Exception(f"Invalid object type {fa.related_object_type}")
        return value

    def get_mrr_attribute(self):
        return FilterableAttribute.objects.get_mrr_attribute(self.customer)

    def get_mrr(self):
        fa = self.get_mrr_attribute()
        return self.get_attribute_value_from_company_or_user(fa)

    def get_mrr_fast(self, fa):
        return self.get_attribute_value_from_company_or_user(fa)

    def get_plan_attribute(self):
        return FilterableAttribute.objects.get_plan_attribute(self.customer)

    def get_plan(self):
        fa = self.get_plan_attribute()
        return self.get_attribute_value_from_company_or_user(fa)

    def get_plan_fast(self, fa):
        return self.get_attribute_value_from_company_or_user(fa)

    def get_name_or_email(self):
        return self.name or self.email or ""

    def get_first_name(self):
        if self.name:
            first_name = self.name.split()[0]
        else:
            first_name = ""
        return first_name.strip()

    def get_friendly_name_email_and_company(self):
        if self.name and self.email:
            if self.company:
                label = f"{self.name} @ {self.company.name} ({self.email})"
            else:
                label = f"{self.name} ({self.email})"
        elif self.name:
            label = f"{self.name}"
            if self.company:
                label = label + f" @ {self.company.name}"
        else:
            label = f"{self.email}"
            if self.company:
                label = label + f" @ {self.company.name}"
        return label

    def get_dropdown_display(self):
        if self.name and self.email:
            label = f"{self.name} ({self.email})"
        elif self.name:
            label = f"{self.name}"
        else:
            label = f"{self.email}"
        return label

    def __str__(self):
        return self.email or self.name or self.remote_id or "unnamed!"
