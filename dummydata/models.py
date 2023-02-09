import os
import csv
from django.db import models
from django.conf import settings
from accounts.models import Customer
from appaccounts.models import AppUser, AppCompany, FilterableAttribute
from feedback.models import Feedback, FeedbackImporter, FeatureRequest, Theme
from integrations.shared.importers import BaseImporter, AttributeMapper, AttributeMapping

class DummyDataCompanyAttributeMapper(AttributeMapper):
    OBJECT_TYPE = FilterableAttribute.OBJECT_TYPE_APPCOMPANY

    STOCK_ATTRIBUTE_MAPPINGS = (
        AttributeMapping('monthly_spend', FilterableAttribute.ATTRIBUTE_TYPE_FLOAT, FilterableAttribute.WIDGET_TYPE_GROUPED_SELECT, False, is_mrr=True),
        AttributeMapping('plan', FilterableAttribute.ATTRIBUTE_TYPE_STR, FilterableAttribute.WIDGET_TYPE_SELECT, False, is_plan=True),
    )

    def get_filterable_attributes_as_dict(self):
        filterable_attributes = dict()
        filterable_attributes['monthly_spend'] = float(self.obj.get('monthly_spend', 0.0)) or None
        filterable_attributes['plan'] = self.obj.get('plan', None)
        return filterable_attributes

class DummyDataManager(models.Manager):
    def load_data(self, customer):
        f = open(os.path.join(settings.BASE_DIR, 'dummydata/dummydata.csv'))
        reader = csv.DictReader(f)

        # Need to make things in bottom up dependency order.

        # AppCompany
        # HACK: Lie and say these are from Intercom. Should create a DummyData importer type.
        source = FeedbackImporter.objects.get(name="Intercom")
        for item in reader:
            app_company, created = AppCompany.objects.get_or_create(
                customer=customer,
                name=item['AppCompany'],
            )

            if created:
                DummyData.objects.create(customer=customer, app_company=app_company)
                mapper = DummyDataCompanyAttributeMapper(customer, item, source)
                mapper.create_filterable_attributes()
                app_company.filterable_attributes = mapper.get_filterable_attributes_as_dict()
                app_company.save()

        # AppUser
        f.seek(0)
        reader = csv.DictReader(f)
        for item in reader:
            app_company = AppCompany.objects.get(customer=customer, name=item['AppCompany'])
            app_user, created = AppUser.objects.get_or_create(
                customer=customer,
                company=app_company,
                name=item['AppUser'],
                email=item['email'])
            if created:
                DummyData.objects.create(customer=customer, app_user=app_user)

        # Theme
        f.seek(0)
        reader = csv.DictReader(f)
        for item in reader:
            if item['Theme']:
                theme, created = Theme.objects.get_or_create(
                    customer=customer,
                    title=item['Theme'])
                if created:
                    DummyData.objects.create(customer=customer, theme=theme)

        # FeatureRequest
        f.seek(0)
        reader = csv.DictReader(f)
        for item in reader:
            if not item['FeatureRequest']:
                continue

            if item['Theme']:
                theme = Theme.objects.get(customer=customer, title=item['Theme'])
            else:
                theme = None

            if item['feature_request_state']:
                assert(item['feature_request_state'] in FeatureRequest.STATE_KEYS)
            if item['priority']:
                assert(item['priority'] in FeatureRequest.PRIORITY_KEYS)
            if item['effort']:
                assert(item['effort'] in FeatureRequest.EFFORT_KEYS)

            fr, created = FeatureRequest.objects.get_or_create(
                customer=customer,
                title=item['FeatureRequest'],
                state=item['feature_request_state'],
                priority=item['priority'],
                effort=item['effort'])
            if created:
                if theme:
                    fr.themes.add(theme)
                DummyData.objects.create(customer=customer, feature_request=fr)

        # Feedback
        f.seek(0)
        reader = csv.DictReader(f)
        for item in reader:
            if item['FeatureRequest']:
                fr = FeatureRequest.objects.get(customer=customer, title=item['FeatureRequest'])
            else:
                fr = None
            app_user = AppUser.objects.get(customer=customer, email=item['email'])

            if item['feedback_state']:
                assert(item['feedback_state'] in Feedback.STATE_KEYS)
            if item['type']:
                assert(item['type'] in Feedback.TYPE_KEYS)

            feedback, created = Feedback.objects.get_or_create(
                customer=customer,
                feature_request=fr,
                user=app_user,
                problem=item['Feedback'],
                state=item['feedback_state'],
                feedback_type=item['type'])
            if created:
                DummyData.objects.create(customer=customer, feedback=feedback)


    def delete_data(self, customer):
        to_delete = self.get_queryset().filter(customer=customer)
        for item in to_delete:
            try:
                item.reference.delete()
            except (AppUser.DoesNotExist, AppCompany.DoesNotExist, Feedback.DoesNotExist,
                FeatureRequest.DoesNotExist, Theme.DoesNotExist):
                # Cacades mean that deleting something like an AppCompany might also
                # delete an AppUser. We can savely ignore that.
                pass
            item.delete()

class DummyData(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)

    app_user = models.ForeignKey(AppUser, null=True, blank=True, on_delete=models.CASCADE)
    app_company = models.ForeignKey(AppCompany, null=True, blank=True, on_delete=models.CASCADE)
    feedback = models.ForeignKey(Feedback, null=True, blank=True, on_delete=models.CASCADE)
    feature_request = models.ForeignKey(FeatureRequest, null=True, blank=True, on_delete=models.CASCADE)
    theme = models.ForeignKey(Theme, null=True, blank=True, on_delete=models.CASCADE)

    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, editable=False)

    objects = DummyDataManager()

    @property
    def reference(self):
        if self.app_user is not None:
            return self.app_user
        if self.app_company is not None:
            return self.app_company
        if self.feedback is not None:
            return self.feedback
        if self.feature_request is not None:
            return self.feature_request
        if self.theme is not None:
            return self.theme

        raise AssertionError("No item referenced in dummy data row")