from django.utils import timezone
from rest_framework import serializers
from rest_framework.compat import unicode_to_repr
from rest_framework.fields import empty

from accounts.models import OnboardingTask
from appaccounts.models import AppUser
from feedback.models import FeatureRequest, Feedback, Theme
from internal_analytics import tracking


class CurrentCustomerDefault(object):
    def set_context(self, serializer_field):
        self.customer = serializer_field.context["request"].user.customer

    def __call__(self):
        return self.customer

    def __repr__(self):
        return unicode_to_repr("%s()" % self.__class__.__name__)


class CustomerFilteredPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        request = self.context.get("request", None)
        queryset = super(CustomerFilteredPrimaryKeyRelatedField, self).get_queryset()
        if not request or not queryset:
            return None
        return queryset.filter(customer=request.user.customer)


# class UserSerializer(serializers.ModelSerializer):
#     permissions = serializers.SerializerMethodField()
#     customer_name = serializers.SerializerMethodField()

#     def get_customer_name(self, obj):
#         return obj.customer.name

#     def get_permissions(self, obj):
#         return obj.get_permissions()

#     class Meta:
#         model = User
#         fields = ('customer', 'customer_name', 'id', 'email', 'first_name', 'last_name', 'role', 'permissions')


class TenantSerializer(serializers.ModelSerializer):
    def validate_customer(self, value):
        if value:
            if self.context.get("request").user.customer != value:
                raise serializers.ValidationError("Invalid customer.")
        return value

    def validate_tenant_for_field(self, value, error_name):
        if value:
            if self.context.get("request").user.customer != value.customer:
                raise serializers.ValidationError(f"Invalid {error_name}.")
        return value


class AppUserSerializer(TenantSerializer):
    customer = serializers.HiddenField(default=CurrentCustomerDefault(),)

    company_name = serializers.SerializerMethodField()

    def get_company_name(self, obj):
        return obj.company.name if obj.company else ""

    def validate_company(self, value):
        return self.validate_tenant_for_field(value, "company")

    class Meta:
        model = AppUser
        fields = ("customer", "id", "company", "company_name", "name", "email")


class FeatureRequestSerializer(serializers.ModelSerializer):
    customer = serializers.HiddenField(default=CurrentCustomerDefault(),)

    state_display = serializers.SerializerMethodField()
    priority_display = serializers.SerializerMethodField()

    def get_state_display(self, obj):
        return obj.get_state_display()

    def get_priority_display(self, obj):
        return obj.get_priority_display()

    class Meta:
        model = FeatureRequest
        fields = (
            "customer",
            "id",
            "title",
            "description",
            "state",
            "state_display",
            "priority",
            "priority_display",
        )


class FeedbackSerializer(serializers.ModelSerializer):
    customer = serializers.HiddenField(default=CurrentCustomerDefault(),)

    feedback_type_display = serializers.SerializerMethodField()

    def get_feedback_type_display(self, obj):
        return obj.get_feedback_type_display()

    class Meta:
        model = Feedback
        fields = (
            "customer",
            "id",
            "problem",
            "solution",
            "feature_request",
            "feedback_type",
            "feedback_type_display",
            "user",
            "created",
            "notified_at",
        )


class DetailedFeedbackSerializer(serializers.ModelSerializer):
    customer = serializers.HiddenField(default=CurrentCustomerDefault(),)

    feature_request = FeatureRequestSerializer()
    user = AppUserSerializer()
    feedback_type_display = serializers.SerializerMethodField()

    def get_feedback_type_display(self, obj):
        return obj.get_feedback_type_display()

    class Meta:
        model = Feedback
        fields = (
            "customer",
            "id",
            "problem",
            "solution",
            "feature_request",
            "feedback_type",
            "feedback_type_display",
            "user",
            "created",
            "notified_at",
        )


class ChromeExtensionFeedbackSerializer(serializers.Serializer):
    app_user_id = serializers.IntegerField(allow_null=True)
    app_user_name = serializers.CharField(allow_blank=True)
    app_user_email = serializers.EmailField(allow_blank=True)
    problem = serializers.CharField()
    #    solution = serializers.CharField(allow_blank=True)
    feature_request_id = serializers.IntegerField(allow_null=True)
    feature_request_title = serializers.CharField(allow_blank=True)
    source_url = serializers.CharField(allow_blank=True)
    feedback_type = serializers.ChoiceField(choices=Feedback.TYPE_CHOICES)

    def validate_belongs_to_tenant(self, model_class, value):
        request = self.context.get("request")

        if value is None:
            # No row means can't be on the wrong tenant
            return

        if not (request and request.user and request.user.customer):
            raise serializers.ValidationError("Invalid request")

        if not model_class.objects.filter(
            customer=request.user.customer, pk=value
        ).exists():
            raise serializers.ValidationError("Invalid id.")

    def validate_app_user_id(self, value):
        self.validate_belongs_to_tenant(AppUser, value)
        return value

    def validate_feature_request_id(self, value):
        self.validate_belongs_to_tenant(FeatureRequest, value)
        return value

    def validate_feature_request_title(self, value):
        if value:
            permissions = self.context.get("request").user.get_permissions()
            if not permissions["can_create_feature_request"]:
                raise serializers.ValidationError(
                    "You don't have permissions to create Feature Requests."
                )
        return value

    def validate(self, data):
        if data["feature_request_id"] is not None and data["feature_request_title"]:
            raise serializers.ValidationError(
                "You can't specify a value for feature_request_title and feature_request_id."
            )

        if data["app_user_id"] is not None and (
            data["app_user_name"] or data["app_user_email"]
        ):
            raise serializers.ValidationError(
                "You can't specify a value for app_user_email or app_user_name and app_user_id."
            )

        if (
            data["app_user_id"] is None
            and data["app_user_name"] == ""
            and data["app_user_email"] == ""
        ):
            raise serializers.ValidationError(
                "You need to specify either a name or an email for the app_user."
            )

        return data

    def save(self):
        user = self.context.get("request").user
        customer = user.customer
        if self.validated_data["feature_request_title"]:
            feature_request, created = FeatureRequest.objects.get_or_create(
                customer=customer, title=self.validated_data["feature_request_title"]
            )

            if created:
                tracking.feature_request_created(user, tracking.EVENT_SOURCE_CE)
            fr_id = feature_request.pk
        else:
            fr_id = self.validated_data["feature_request_id"]

        if self.validated_data["app_user_email"]:
            app_user, created = AppUser.objects.update_or_create(
                customer=customer,
                email=self.validated_data["app_user_email"],
                defaults={"name": self.validated_data["app_user_name"],},
            )
            app_user_id = app_user.pk
        elif self.validated_data["app_user_name"]:
            try:
                app_user, created = AppUser.objects.update_or_create(
                    customer=customer,
                    name=self.validated_data["app_user_name"],
                    email=None,
                )
            except AppUser.MultipleObjectsReturned:
                app_user = AppUser.objects.filter(
                    customer=customer,
                    name=self.validated_data["app_user_name"],
                    email=None,
                )[0]
            app_user_id = app_user.pk
        else:
            app_user_id = self.validated_data["app_user_id"]

        feedback = Feedback(
            customer=customer,
            created_by=user,
            user_id=app_user_id,
            feature_request_id=fr_id,
            problem=self.validated_data["problem"],
            solution="",  # self.validated_data['solution'],
            source_url=self.validated_data["source_url"],
            feedback_type=self.validated_data["feedback_type"],
        )
        feedback.save()

        total_created_by_user = Feedback.objects.filter(
            customer=customer, created_by=user
        ).count()
        first_entry = total_created_by_user == 1

        tracking.feedback_created(
            user.id, user.customer, feedback, tracking.EVENT_SOURCE_CE
        )

        OnboardingTask.objects.filter(
            customer=customer, task_type=OnboardingTask.TASK_CREATE_FEEDBACK_CE
        ).update(completed=True, updated=timezone.now())

        return {"id": feedback.pk, "first_entry": first_entry}


class OneShotFeedbackSerializer(serializers.Serializer):
    problem = serializers.CharField()
    feedback_type = serializers.ChoiceField(choices=Feedback.TYPE_CHOICES)
    state = serializers.ChoiceField(
        choices=Feedback.STATE_CHOICES,
        default=Feedback.ACTIVE,
        allow_blank=True,
        required=False,
    )
    source_url = serializers.CharField(allow_blank=True, required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    person_name = serializers.CharField(allow_blank=True, required=False)
    person_email = serializers.EmailField(allow_blank=True, required=False)
    feature_request_title = serializers.CharField(allow_blank=True, required=False)

    def __init__(self, instance=None, data=empty, **kwargs):
        # HACK: this little shit sandwitch makes our handling of the tags field
        # a little more forgiving. One key usecase for this api call is Zapier.
        # When using Zapier's built in Webhooks app you can't send a JSON list
        # unless you drop down to their painful custom response feature.
        # To get around that we let you send a string or a list.
        # Example: if you should send ['red', 'green'] we let you send
        # "red,green" and turn it into ['red', 'green'].
        if "tags" in data and type(data["tags"]) is str:
            data["tags"] = [tag.strip() for tag in data["tags"].split(",")]
        super().__init__(instance=instance, data=data, **kwargs)

    def save(self):
        user = self.context.get("request").user
        customer = user.customer
        fr_title = self.validated_data.get("feature_request_title", "")
        if fr_title:
            feature_request, created = FeatureRequest.objects.get_or_create(
                customer=customer, title__iexact=fr_title, defaults={"title": fr_title,}
            )

            if created:
                tracking.feature_request_created(user, tracking.EVENT_SOURCE_API)
            fr_id = feature_request.pk
        else:
            fr_id = None

        email = self.validated_data.get("person_email", "")
        name = self.validated_data.get("person_name", "")
        if email:
            app_user, created = AppUser.objects.update_or_create(
                customer=customer,
                email__iexact=email,
                defaults={"email": email, "name": name,},
            )
            app_user_id = app_user.pk
        elif name:
            app_user, created = AppUser.objects.get_or_create(
                customer=customer, name=name, defaults={"email": email or None,}
            )
            app_user_id = app_user.pk
        else:
            app_user_id = None

        feedback = Feedback(
            customer=customer,
            created_by=user,
            user_id=app_user_id,
            feature_request_id=fr_id,
            problem=self.validated_data["problem"],
            source_url=self.validated_data.get("source_url", ""),
            feedback_type=self.validated_data["feedback_type"],
            state=self.validated_data["state"],
            source_username="Savio API",
        )
        feedback.save(override_auto_triage=True)

        for theme_name in self.validated_data.get("tags", list()):
            defaults = {
                "title": theme_name,
            }

            theme, created = Theme.objects.get_or_create(
                customer=user.customer, title__iexact=theme_name, defaults=defaults
            )
            feedback.themes.add(theme)

        tracking.feedback_created(
            user.id, user.customer, feedback, tracking.EVENT_SOURCE_API
        )
        return {"id": feedback.pk}
