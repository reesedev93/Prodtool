import logging
import requests
from datetime import datetime, timedelta, timezone
from django.conf import settings
from django.db import IntegrityError
from django.template.defaultfilters import truncatechars
from django.urls import reverse
from html2text import html2text
from requests.exceptions import ReadTimeout
from time import sleep
from accounts.models import OnboardingTask
from appaccounts.models import AppUser, AppCompany
from integrations.shared.importers import BaseImporter
from feedback.models import Feedback
from .api import Client, ApiException

class HelpScoutFeedbackImporter(BaseImporter):
    def __init__(self, cfis):
        self.settings = cfis
        self.customer = cfis.customer
        self.last_requested_at = cfis.last_requested_at

        self.client = Client(cfis.api_key, cfis.refresh_token, settings.HELPSCOUT_CLIENT_ID, settings.HELPSCOUT_CLIENT_SECRET, self.settings.save_refreshed_tokens)
        self.source = cfis.importer
        self.feedback_tag_name = cfis.feedback_tag_name
        self.feedback_hashtag = f"#{self.feedback_tag_name}"

    def execute(self, all_data=False):
        self.logger.info(f"Starting HelpScout feedback importer for {self.customer.name}!")
        self.start_time = datetime.now(timezone.utc)

        self.total_new_users = 0

        # NB: need to be careful here to avoid race condition
        # where CFIS.feedback_tag_name gets wiped as during
        # onboarding we launch an import *before* the tag
        # name has been set and then immeidately get the user
        # to set their tag name. Sadly Model.save() doens't
        # do dirty checking and will just have all fields
        # the background job typically will happen second
        # and it won't have a tag name set.
        # See: https://code.djangoproject.com/ticket/27017
        self.settings.last_requested_at = self.start_time
        self.settings.save(update_fields=('last_requested_at',))

        elapsed_time = datetime.now(timezone.utc) - self.start_time
        self.logger.info(f"Finished running HelpScout feedback importer for {self.customer.name}! Runtime: {elapsed_time}. Users: {self.total_new_users}.")

    def get_full_message(self, convo_json):
        message = ""
        for thread in convo_json.get("threads", list()):
            if thread["body"] and thread["type"] in ("customer", "beaconchat"):
                message += self.format_message_part(thread["createdBy"], thread["createdAt"], thread["body"])
        return message.strip()

    def get_friendly_name(self, user):
        first_name = user.get('firstName', '')
        last_name = user.get('lastName', '')
        email = user.get('email', '')

        name = f"{first_name} {last_name}".strip()

        if name and email:
            fullname = f"{name} ({email})"
        elif email:
            fullname = email
        elif name:
            fullname = name
        else:
            fullname = 'N/A'

        return fullname

    def format_message_part(self, createdby, createdat, message):
        friendly_name = self.get_friendly_name(createdby)

        return f"**From**: {friendly_name}<br>**Date**: {createdat}<br><br>{message}<br><br>"

    def handle_conversation_created(self, json):
        created = False
        if json['type'] == 'chat':
            created = self.handle_conversation_admin_noted(json)
            if not created:
                created = self.handle_conversation_tagged(json)
        return created

    def handle_conversation_tagged(self, json):
        created = False
        if self.feedback_tag_name and self.feedback_tag_name in json['tags']:
            message = self.get_full_message(json)
            message = html2text(message)
            source_url = self.client.get_conversation(json['id']).json()['_links']['web']['href']
            status = json['status']

            try:
                customer_id = json['customer']['id']
                appuser = self.import_customer(customer_id)
            except KeyError:
                appuser = None

            defaults = {
                'user': appuser,
                'source_url': source_url,
                'source_username': 'Savio Help Scout Bot',
            }
            feedback, created = Feedback.objects.get_or_create(customer=self.customer, problem=message, defaults=defaults)
            if created:
                # We don't know who tagged the thread so...
                self.create_ack_note(json['id'], feedback, None, status)
                OnboardingTask.objects.filter(
                    customer=self.customer,
                    task_type=OnboardingTask.TASK_SUBMIT_FEEDBACK_VIA_HELP_DESK).update(completed=True, updated=datetime.now(timezone.utc))

        return created

    def handle_conversation_admin_noted(self, json):
        # The most recent note in the thread will be the one that triggered
        # the web hook. Threads are presorted by date.
        most_recent_note_content = ""
        note = None
        created = False
        for message in json['threads']:
            if message['type'] == 'note':
                most_recent_note_content = message['body']
                note = message
                break

        if self.feedback_hashtag and self.feedback_hashtag in most_recent_note_content:
            note_text = html2text(most_recent_note_content)
            note_text = note_text.replace(self.feedback_hashtag, '').strip()
            source_url = self.client.get_conversation(json['id']).json()['_links']['web']['href']
            status = json['status']

            remote_id = note['createdBy']['id']
            try:
                customer_id = json['customer']['id']
                appuser = self.import_customer(customer_id)
            except KeyError:
                appuser = None

            defaults = {
                'user': appuser,
                'source_url': source_url,
                'source_username': 'Savio Help Scout Bot',
            }
            feedback, created = Feedback.objects.get_or_create(customer=self.customer, problem=note_text, defaults=defaults)
            if created:
                self.create_ack_note(json['id'], feedback, remote_id, status)
                OnboardingTask.objects.filter(
                    customer=self.customer,
                    task_type=OnboardingTask.TASK_SUBMIT_FEEDBACK_VIA_HELP_DESK).update(completed=True, updated=datetime.now(timezone.utc))

        return created

    def create_ack_note(self, conversation_id, feedback, hs_user_id, status):
        summary = feedback.get_problem_snippet()
        savio_link = settings.HOST + reverse('feedback-item', args=[str(feedback.id)])
        ack_message = f"[Savio] Feedback, '{summary}' successfully added. <a href='{savio_link}' rel='nofollow noopener noreferrer' target='_blank'>View in Savio</a>."

        self.client.create_note(ack_message, conversation_id, hs_user_id)

        # There is a bug in HS where if you add a note to a closed ticket it will
        # automatically reopen it. So if the tickets status isn't 'active' before
        # we added the note put the tickets status back to whatever it was before
        # we added the note.
        if status != 'active':
            self.client.update_conversation(conversation_id, '/status', 'replace', status)

    def import_company(self, company_name):
        appcompany = None
        if company_name:
            self.logger.info(f"Importing company: {company_name}")
            defaults = {
                'name': company_name[:255],
            }

            try:
                appcompany, created = AppCompany.objects.update_or_create(
                    customer=self.customer, remote_id=company_name.upper(), defaults=defaults)
                # mapper = IntercomCompanyAttributeMapper(self.customer, company, self.source)
                # mapper.create_filterable_attributes()
                # appcompany.filterable_attributes = mapper.get_filterable_attributes_as_dict()
                # appcompany.save()
            except IntegrityError as e:
                self.logger.warn(f"Skipped creating AppCompany in Help Scout importer do to Integrity error. Do they have duplicate internal_ids? Details: {e}.")
        else:
            self.logger.info(f"Skipped company in Help Scout because it has no name.")
        return appcompany

    def import_customer(self, customer_id):
        # self.sleep_if_rate_limit()
        self.logger.info(f"Importing customer: {customer_id}")
        customer = self.client.get_customer(customer_id).json()

        company_name = customer.get('organization', '')
        company = self.import_company(company_name)
        try:
            # HS users have a list of emails. We only support one so
            # just grab the first. Hopefully the sort is stable.
            email = customer['_embedded']['emails'][0]['value']
        except (KeyError, IndexError) as e:
            email = None

        try:
            # HS users have a list of phones. We only support one so
            # just grab the first.
            phone = customer['_embedded']['phones'][0]['value']
        except (KeyError, IndexError) as e:
            phone = ''

        first_name = customer.get('firstName', '')
        last_name = customer.get('lastName', '')
        name = f"{first_name} {last_name}".strip()

        appuser = None
        try:
            appuser, created = AppUser.objects.update_or_create_by_email_or_remote_id(
                customer=self.customer,
                email=email,
                remote_id=customer_id,
                defaults= {
                    'name': name[:255],
                    'phone': phone[:30],
                    'company': company,
                }
            )
            # mapper = IntercomUserAttributeMapper(self.customer, user, self.source)
            # mapper.create_filterable_attributes()
            # appuser.filterable_attributes = mapper.get_filterable_attributes_as_dict()
            # appuser.save()
        except IntegrityError as e:
            self.logger.warn(f"Skipped creating AppUser in Intercom importer do to Integrity error. Do they have duplicate internal_ids? Details: {e}.")
        return appuser

    def handle_webhook(self, json, secret=None, event=None):
        # https://developer.helpscout.com/webhooks/

        print(json)

        try:
            if event == 'convo.note.created':
                self.handle_conversation_admin_noted(json)
            elif event == 'user.created':
                self.handle_user_created_webook(json)
            elif event == 'convo.tags':
                self.handle_conversation_tagged(json)
            elif event == 'convo.created':
                self.handle_conversation_created(json)
            else:
                raise Exception(f"Unsupported Help Scout web hook topic #{event}")
        except ApiException as e:
            if e.status_code == 401:
                self.logger.info(f"Failed to handle webhook due to permissions issue. Likely invalid token that couldn't be refreshed. Customer: {self.customer.name}.")
            else:
                raise