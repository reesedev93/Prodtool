import logging
import requests
import pytz
from django.conf import settings
from django.db import models, IntegrityError
from datetime import datetime, timedelta, timezone
from appaccounts.models import AppUser, AppCompany, FilterableAttribute
from integrations.shared.importers import BaseImporter, AttributeMapper, AttributeMapping
from feedback.models import Feedback

logger = logging.getLogger(__name__)

class SegmentIdentifyAttributeMapper(AttributeMapper):
    OBJECT_TYPE = FilterableAttribute.OBJECT_TYPE_APPUSER

    EXCLUSIONS = (
        'address',
        'avatar',
        'birthday',
        'company',
        'createdAt',
        'description',
        'email',
        'firstName',
        'id',
        'lastName',
        'name',
        'phone',
        'username',
        'website',
    )

    EXCLUSION_TYPES = (dict, list) # We only support simple types

    STOCK_ATTRIBUTE_MAPPINGS = ()

    # Although Segment reserves certain names they aren't really guaranteed to be there
    # STOCK_ATTRIBUTE_MAPPINGS = (
    #     AttributeMapping('gender', FilterableAttribute.ATTRIBUTE_TYPE_STR, FilterableAttribute.WIDGET_TYPE_SELECT, False),
    #     AttributeMapping('title', FilterableAttribute.ATTRIBUTE_TYPE_STR, FilterableAttribute.WIDGET_TYPE_SELECT, False),
    # )

    def get_filterable_attributes_as_dict(self):
        filterable_attributes = dict()
        for name, value in self.obj['traits'].items():
            if value is None or type(value) in self.EXCLUSION_TYPES or name in self.get_exclusions():
                continue
            filterable_attributes[name] = value
        return filterable_attributes

class SegmentGroupAttributeMapper(AttributeMapper):
    OBJECT_TYPE = FilterableAttribute.OBJECT_TYPE_APPCOMPANY

    EXCLUSIONS = (
        'address',
        'avatar',
        'createdAt',
        'description',
        'email',
        'id',
        'name',
        'phone',
        'website',
    )

    EXCLUSION_TYPES = (dict, list) # We only support simple types

    STOCK_ATTRIBUTE_MAPPINGS = ()

    # Although Segment reserves certain names they aren't really guaranteed to be there
    # STOCK_ATTRIBUTE_MAPPINGS = (
    #     AttributeMapping('employees', FilterableAttribute.ATTRIBUTE_TYPE_STR, FilterableAttribute.WIDGET_TYPE_SELECT, False),
    #     AttributeMapping('industry', FilterableAttribute.ATTRIBUTE_TYPE_STR, FilterableAttribute.WIDGET_TYPE_SELECT, False),
    #     AttributeMapping('plan', FilterableAttribute.ATTRIBUTE_TYPE_STR, FilterableAttribute.WIDGET_TYPE_SELECT, False),
    # )

    def get_filterable_attributes_as_dict(self):
        filterable_attributes = dict()
        for name, value in self.obj['traits'].items():
            if value is None or type(value) in self.EXCLUSION_TYPES or name in self.get_exclusions():
                continue
            filterable_attributes[name] = value
        return filterable_attributes

class SegmentFeedbackImporter(BaseImporter):
    def __init__(self, cfis):
        self.settings = cfis
        self.customer = cfis.customer
        self.last_requested_at = cfis.last_requested_at or datetime.min.replace(tzinfo=pytz.UTC)
        self.api_key = cfis.api_key
        self.source = cfis.importer

    def handle_webhook(self, json, secret=None, event=None):
        event_type = json.get('type', '')
        if event_type == 'identify':
            self.handle_identify_webhook(json)
        elif event_type == 'group':
            self.handle_group_webhook(json)
        elif event_type == 'delete':
            self.handle_delete_webhook(json)
        else:
            raise Exception(f"{json[type]} isn't a valid type for Segment")

    def handle_identify_webhook(self, json):
        user_id = json.get('userId', '') or json.get('user_id', '')
        if 'traits' in json:
            email = json['traits'].get('email', None)
            phone = json['traits'].get('phone', '') or ''
            phone = phone[:30]
            name = json['traits'].get('name', '') or ''

        if user_id and (email or name):
            try:
                appuser, created = AppUser.objects.update_or_create_by_email_or_internal_id(
                    customer=self.customer,
                    internal_id=user_id,
                    email=email,
                    defaults={
                        'phone': phone,
                        'name': name[:255],
                    }
                )
                mapper = SegmentIdentifyAttributeMapper(self.customer, json, self.source)
                mapper.create_filterable_attributes()
                appuser.filterable_attributes = mapper.get_filterable_attributes_as_dict()
                appuser.save()
            except IntegrityError:
                # We only allow one AppUser with a give email
                logger.warning(f'IntegrityError: skipped creating an app user in SegmentFeedbackImporter likely multiple users with the same email address. {json}')
        else:
            logger.info(f'Skipped creating an AppUser in SegmentFeedbackImporter. Missing userId or one of email or name. {json}')

    def handle_group_webhook(self, json):
        group_id = json.get('groupId', '')

        if 'traits' in json:
            name = json['traits'].get('name', '') or ''
            plan = json['traits'].get('plan', '') or ''
            monthly_spend = json['traits'].get('total billed', None)

        if group_id and name:
            company, created = AppCompany.objects.update_or_create(
                customer=self.customer,
                internal_id=group_id,
                defaults={
                    'name': name[:255],
                    'plan': plan,
                    'monthly_spend': monthly_spend,
                }
            )
            mapper = SegmentGroupAttributeMapper(self.customer, json, self.source)
            mapper.create_filterable_attributes()
            company.filterable_attributes = mapper.get_filterable_attributes_as_dict()
            company.save()

            user_id = json.get('userId', '')
            if user_id:
                try:
                    user = AppUser.objects.get(
                        customer=self.customer,
                        internal_id=user_id)
                    user.company = company
                    user.save()
                except AppUser.DoesNotExist:
                    logger.info(f'Skipped linking AppUser to AppCompany in SegmentFeedbackImporter. No user for userId. {json}')
            else:
                logger.info(f'Skipped linking AppUser to AppCompany in SegmentFeedbackImporter. No userId. {json}')

        else:
            logger.info(f'Skipped creating an AppCompany in SegmentFeedbackImporter. Missing groupId and name. {json}')

    def handle_delete_webhook(self, json):
        user_id = json.get('userId', '') or json.get('user_id', '')
        if user_id:
            AppUser.objects.delete(customer=self.customer, internal_id=user_id)
        else:
            logger.info(f'Skipped deleting an AppUser in SegmentFeedbackImporter. Missing userId. {json}')

    def execute(self, all_data=False):
        # Segment currently only handles webhooks
        pass
