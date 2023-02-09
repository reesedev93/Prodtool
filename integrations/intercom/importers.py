import uuid
from datetime import datetime, timezone
from time import sleep

import pytz
import requests
from django.conf import settings
from django.db import IntegrityError
from django.urls import reverse
from html2text import html2text
from intercom.client import Client
from intercom.errors import (
    ResourceNotFound,
    TokenNotFoundError,
    TokenUnauthorizedError,
    UnexpectedError,
)

from accounts.models import OnboardingTask
from appaccounts.models import AppCompany, AppUser, FilterableAttribute
from feedback.models import FeatureRequest, Feedback
from integrations.shared.importers import (
    AttributeMapper,
    AttributeMapping,
    BaseImporter,
)


def get_workspace_id(token):
    return Client(personal_access_token=token).contacts.all()[0].workspace_id


class IntercomCompanyAttributeMapper(AttributeMapper):
    OBJECT_TYPE = FilterableAttribute.OBJECT_TYPE_APPCOMPANY

    STOCK_ATTRIBUTE_MAPPINGS = (
        AttributeMapping(
            "monthly_spend",
            FilterableAttribute.ATTRIBUTE_TYPE_FLOAT,
            FilterableAttribute.WIDGET_TYPE_GROUPED_SELECT,
            False,
            is_mrr=True,
        ),
        AttributeMapping(
            "plan",
            FilterableAttribute.ATTRIBUTE_TYPE_STR,
            FilterableAttribute.WIDGET_TYPE_SELECT,
            False,
            is_plan=True,
        ),
    )

    def get_filterable_attributes_as_dict(self):
        filterable_attributes = dict()
        filterable_attributes["monthly_spend"] = self.obj.monthly_spend
        try:
            filterable_attributes["plan"] = self.obj.plan.name
        except AttributeError:
            # If they don't have a plan you get a {} instead of a plan object.
            filterable_attributes["plan"] = ""
        for name, value in self.obj.attributes["custom_attributes"].items():
            if value is None:
                continue
            filterable_attributes[name] = value
        return filterable_attributes


class IntercomUserAttributeMapper(AttributeMapper):
    OBJECT_TYPE = FilterableAttribute.OBJECT_TYPE_APPUSER

    STOCK_ATTRIBUTE_MAPPINGS = ()

    def get_filterable_attributes_as_dict(self):
        filterable_attributes = dict()
        for name, value in self.obj.attributes["custom_attributes"].items():
            if value is None:
                continue
            filterable_attributes[name] = value
        return filterable_attributes


class IntercomFeedbackImporter(BaseImporter):
    MAX_RETRIES = 5
    RETRY_COOL_OFF = 5  # seconds
    RATE_LIMIT_COOL_OFF = 11
    RATE_LIMIT_LOWER_BOUND = 5

    def __init__(self, cfis):
        self.settings = cfis
        self.customer = cfis.customer
        self.last_requested_at = cfis.last_requested_at or datetime.min.replace(
            tzinfo=pytz.UTC
        )
        self.api_key = cfis.api_key
        self.source = cfis.importer
        self.feedback_tag_name = cfis.feedback_tag_name

        if self.feedback_tag_name:
            self.feedback_hashtag = f"#{self.feedback_tag_name}"
        else:
            self.feedback_hashtag = ""

        self.client = Client(personal_access_token=cfis.api_key)
        self.have_used_scroll = False

    def sleep_if_rate_limit(self):
        self.logger.info(self.client.rate_limit_details)
        if (
            "remaining" in self.client.rate_limit_details
            and self.client.rate_limit_details["remaining"]
            < self.RATE_LIMIT_LOWER_BOUND
        ):
            self.logger.info(
                f"Rate limit hit. Cooling off for {self.RATE_LIMIT_COOL_OFF}."
            )
            sleep(self.RATE_LIMIT_COOL_OFF)

    def total_new_companies(self):
        return AppCompany.objects.filter(
            customer=self.customer, created__gte=self.start_time
        ).count()

    def total_new_users(self):
        return AppUser.objects.filter(
            customer=self.customer, created__gte=self.start_time
        ).count()

    def import_companies(self):
        self.logger.info("Starting company processing.")
        for company in self.get_company_collection():
            if company.updated_at < self.last_requested_at:
                self.logger.info(
                    f"Done! No more company changes. Broke at {company.id}."
                )
                break

            self.import_company(company)
        self.logger.info("Finihsed company processing.")

    def force_scroll(self):
        force_scroll_customers = ("Housecall Pro",)

        days_since_last_synced = (self.start_time - self.last_requested_at).days
        force_scroll = self.customer.name in force_scroll_customers
        if force_scroll and days_since_last_synced > 0:
            force = True
        else:
            force = False
        return force

    def never_use_scroll(self):
        never = list()
        return self.customer.name in never

    def use_scroll(self):
        first_run = self.last_requested_at == datetime.min.replace(tzinfo=pytz.UTC)
        if self.never_use_scroll():
            return False
        elif first_run:
            return True
        elif self.force_scroll():
            return True
        else:
            return False

    def get_company_collection(self):
        # NB: the "offical" version doesn't support the scroll API so we've forked
        # and merged a PR that does. We should switch back to their version
        # (https://github.com/intercom/python-intercom) once they do.

        # If we are importing all data (first time or forced) we need to use
        # the scroll api to avoid rate limits. Subsequent imports shouldn't matter
        # as we are only grabbing what's new since last import. We don't want to
        # use the scroll api all the time because you can only have one scroll
        # open at a time.
        if self.use_scroll():
            self.logger.info("Using company scroll API.")
            companies = self.client.companies.scroll()
            self.have_used_scroll = True
        else:
            self.logger.info("Using regular company collection API.")
            companies = self.client.companies.find_all(sort="updated_at", order="desc")
        return companies

    def import_company(self, company):
        self.sleep_if_rate_limit()
        # Bizarely companies cannot have a name. If that's the case
        # just skip over that company.
        try:
            company_name = company.name
        except AttributeError:
            company_name = ""

        if company_name:
            self.logger.info(f"Importing company: {company_name}")
            try:
                plan = company.plan.name
            except AttributeError:
                # plan is an empty dict if one isn't set
                plan = ""
            defaults = {
                "name": company_name[:255],
                "plan": plan,
                "monthly_spend": company.monthly_spend,
                "internal_id": company.company_id or None,
            }

            try:
                appcompany, created = AppCompany.objects.update_or_create(
                    customer=self.customer, remote_id=company.id, defaults=defaults
                )
                mapper = IntercomCompanyAttributeMapper(
                    self.customer, company, self.source
                )
                mapper.create_filterable_attributes()
                appcompany.filterable_attributes = (
                    mapper.get_filterable_attributes_as_dict()
                )
                appcompany.save()
            except IntegrityError as e:
                self.logger.warn(
                    f"Skipped creating AppCompany in Intercom importer do to Integrity error. Do they have duplicate internal_ids? Details: {e}."
                )
        else:
            self.logger.info(
                f"Skipped company with id '{company.id}' because it has no name."
            )

    def import_users(self):
        self.logger.info("Starting user processing.")
        self.logger.info("Using contacts API to get users.")

        query = {"field": "role", "operator": "=", "value": "user"}

        sort = {"field": "updated_at", "order": "descending"}
        users = self.client.contacts.find_all(query=query, sort=sort)

        for user in users:
            if user.updated_at < self.last_requested_at:
                self.logger.info(f"Done! No more new users. Broke at {user.id}")
                break
            self.import_user(user)
        self.logger.info("Finished user processing.")

    def import_user(self, user):
        self.sleep_if_rate_limit()
        self.logger.info(f"Importing user: {user.name}")
        try:
            if user.companies.data:
                company = AppCompany.objects.get(
                    customer=self.customer, remote_id=user.companies.data[0]["id"]
                )
            else:
                company = None
        except AppCompany.DoesNotExist:
            self.logger.info("Company for user did not exist.")
            company = None

        email = user.email or None
        try:
            user_name = user.name or ""
            phone = user.phone or ""
            appuser, created = AppUser.objects.update_or_create_by_email_or_remote_id(
                customer=self.customer,
                email=email,
                remote_id=user.id,
                defaults={
                    "name": user_name[:255],
                    "phone": phone[:30],
                    "company": company,
                    "internal_id": user.external_id or None,
                },
            )
            mapper = IntercomUserAttributeMapper(self.customer, user, self.source)
            mapper.create_filterable_attributes()
            appuser.filterable_attributes = mapper.get_filterable_attributes_as_dict()
            appuser.save()
        except IntegrityError as e:
            self.logger.warn(
                f"Skipped creating AppUser in Intercom importer do to Integrity error. Do they have duplicate internal_ids? Details: {e}."
            )

    def handle_webhook(self, json, secret=None, event=None):
        # If we want to sign the webhook data:
        # https://github.com/intercom-archive/intercom-webhooks/blob/master/python/django/webhook_intercom/webhook/views.py
        self.logger.info(
            f"CFIS Intercom webhook: customer: {self.customer} json: {json}"
        )
        self.logger.info(
            f"CFIS Intercom webhook: customer: {self.customer} feedback tag: {self.feedback_tag_name}"
        )

        if not self.valid_webhook_payload(json):
            self.logger.info("CFIS Intercom webhook: invalid webhook payload")
            raise Exception("Payload failed valid_webhook_payload check.")

        try:
            if json["topic"] == "ping":
                pass
            elif json["topic"] in ("user.created",):
                self.handle_user_created_webook(json)
            elif json["topic"] == "conversation_part.tag.created":
                self.handle_conversation_part_tag_created(json)
            elif json["topic"] == "conversation.admin.noted":
                self.handle_conversation_admin_noted(json)
            else:
                self.logger.info("CFIS Intercom webhook: invalid webhook topic")
                raise Exception(f"Unsupported Intercom web hook topic #{json['topic']}")
        except (TokenUnauthorizedError, TokenNotFoundError):
            self.logger.warn(
                f"CFIS Intercom webhook: Looks like we don't have permissions to access Intercom for {self.customer.name}."
            )
        except UnexpectedError as e:
            if e.context and e.context.get("http_code", None) == 401:
                self.logger.warn(
                    f"CFIS Intercom webhook: Looks like we don't have permissions to access Intercom for {self.customer.name}."
                )
            else:
                raise

    def handle_user_created_webook(self, json):
        try:
            # We only handle one company per user. Take the first.
            # Payload:
            # {'type': 'company',
            #  'company_id': '366',
            #  'id': '5bef8f70d40a4794c606e565',
            #  'name': 'Serenity'}
            self.logger.info(f"Customer: {self.customer}")
            company_data = json["data"]["item"]["companies"]["companies"][0]
            company_id = company_data["id"]
            company = self.client.companies.find(id=company_id)
            self.import_company(company)
        except IndexError:
            company = None

        try:
            user_id = json["data"]["item"]["id"]
            user = self.client.contacts.find(id=user_id)
            self.import_user(user)
        except ResourceNotFound:
            self.logger.warn(
                f"CFIS Intercom webhook: Couldn't lookup contact {user_id} for customer {self.customer}."
            )

    def handle_conversation_part_tag_created(self, json):
        added_tags = json["data"]["item"]["tags_added"]["tags"]
        has_feedback_tag = False
        for added_tag in added_tags:
            if self.is_feedback_tag(added_tag["name"]):
                has_feedback_tag = True
                break

        if has_feedback_tag:
            self.create_feedback_from_intercom_message(json, False)

    def handle_conversation_admin_noted(self, json):
        allowed_part_types = ("note", "note_and_reopen")
        note = json["data"]["item"]["conversation_parts"]["conversation_parts"][0]
        assert note["part_type"] in allowed_part_types
        if self.feedback_hashtag and self.feedback_hashtag in note["body"]:
            self.create_feedback_from_intercom_message(json, True)

    def create_feedback_from_intercom_message(self, json, is_feedback_from_note):
        conversation_id = json["data"]["item"]["id"]
        part = json["data"]["item"]["conversation_parts"]["conversation_parts"][0]
        message = part["body"] or ""
        message = html2text(message)
        if is_feedback_from_note:
            # Strip out the feedback #hashtag
            message = message.replace(self.feedback_hashtag, "").strip()
            admin_id = self.get_note_author_id(json)
        else:
            admin_id = self.get_admin_that_applied_tag(conversation_id)

        try:
            source_url = json["data"]["item"]["links"]["conversation_web"]
        except KeyError:
            source_url = ""

        user = json["data"]["item"]["user"]
        remote_id = user["id"]
        internal_id = user["user_id"] or None
        email = user["email"] or None
        app_user = AppUser.objects.get_best_match_user(
            self.customer, email, remote_id, internal_id
        )
        defaults = {
            "user": app_user,
            "source_url": source_url,
            "source_username": "Savio Intercom Bot",
        }
        feedback, created = Feedback.objects.get_or_create(
            customer=self.customer, problem=message, defaults=defaults
        )
        if created:
            self.create_ack_note(conversation_id, feedback, admin_id)
            OnboardingTask.objects.filter(
                customer=self.customer,
                task_type=OnboardingTask.TASK_SUBMIT_FEEDBACK_VIA_HELP_DESK,
            ).update(completed=True, updated=datetime.now(timezone.utc))

    def create_ack_note(self, conversation_id, feedback, admin_id):
        summary = feedback.get_problem_snippet(snippet_length=30, join_char=" ")
        savio_link = settings.HOST + reverse("feedback-item", args=[str(feedback.id)])
        ack_message = f"[Savio] Feedback, '{summary}' successfully added. <a href='{savio_link}' rel='nofollow noopener noreferrer' target='_blank'>View in Savio</a>."

        self.client.conversations.reply(
            id=conversation_id,
            admin_id=admin_id,
            type="admin",
            message_type="note",
            body=ack_message,
        )

    def is_feedback_tag(self, tag_name):
        return tag_name == self.feedback_tag_name

    def get_note_author_id(self, json):
        return json["data"]["item"]["conversation_parts"]["conversation_parts"][0][
            "author"
        ]["id"]

    def get_admin_that_applied_tag(self, conversation_id):
        convo = self.client.conversations.find(id=conversation_id)
        admin_id = None
        for tag in reversed(convo.tags):  # backwards so we hit neweset first
            if self.is_feedback_tag(tag.name):
                admin_id = tag.applied_by.id
                break
        return admin_id

    def valid_webhook_payload(self, json):
        allowed_webhook_topics = (
            "ping",
            "user.created",
            "conversation_part.tag.created",
            "conversation.admin.noted",
        )
        return (
            json["type"] == "notification_event"
            and json["topic"] in allowed_webhook_topics
        )

    def execute(self, all_data=False):
        if all_data:
            self.last_requested_at = datetime.min.replace(tzinfo=pytz.UTC)
        self.logger.info(
            f"Starting Intercom feedback importer for {self.customer.name}. All data = {all_data}"
        )
        self.start_time = datetime.now(timezone.utc)

        try:
            self.import_companies()
            self.import_users()
            # We aren't importing feedback right now only users and companies
            # self.import_feedack()

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
            self.settings.save(update_fields=("last_requested_at",))

            elapsed_time = datetime.now(timezone.utc) - self.start_time
            self.logger.info(
                f"Finished running Intercom feedback importer for {self.customer.name}! Runtime: {elapsed_time}. Companies: {self.total_new_companies()}. Users: {self.total_new_users()}."
            )
        except (TokenUnauthorizedError, TokenNotFoundError):
            self.logger.warn(
                f"Looks like we don't have permissions to access Intercom for {self.customer.name}."
            )
        except UnexpectedError as e:
            if e.context and e.context.get("http_code", None) == 401:
                self.logger.warn(
                    f"Looks like we don't have permissions to access Intercom for {self.customer.name}."
                )
            else:
                raise

    def get_friendly_name(self, author):
        if author.name and author.email:
            fullname = f"{author.name} ({author.email})"
        elif author.email:
            fullname = author.email
        elif author.name:
            fullname = author.name
        else:
            fullname = "N/A"

        return fullname

    def format_message_part(self, part):
        friendly_name = self.get_friendly_name(part.author)
        return f"**From**: {friendly_name}<br>**Date**: {part.created_at}<br><br>{part.body}<br><br>"

    def get_full_message(self, convo):
        message = ""
        for part in convo.conversation_parts:
            if part.body:
                message += self.format_message_part(part)
        return html2text(message)

    def get_feedback_cutoff(self):
        if Feedback.objects.filter(customer=self.customer).exists():
            cutoff = (
                Feedback.objects.filter(customer=self.customer)
                .order_by("-source_updated")[0]
                .source_updated
            )
        else:
            cutoff = datetime.min.replace(tzinfo=timezone.utc)
        return cutoff

    def get_source_url(self, convo, workspace_id):
        return f"https://app.intercom.com/a/apps/{workspace_id}/inbox/inbox/all/conversations/{convo.id}"

    def import_feedack(
        self, cutoff=None, feedback_regex=None, feature_request_regex=None
    ):
        # E.g.
        # feedback_regex = re.compile(r"^feedback$|^feature request$", re.I)
        # feature_request_regex = re.compile("^(Feedback|Feature Request)\s*-\s*(?P<feature_request_name>.+)$", re.I)

        import_token = str(uuid.uuid4())
        workspace_id = get_workspace_id(self.api_key)

        if not cutoff:
            cutoff = self.get_feedback_cutoff()

        if not feedback_regex:
            default_tag = self.feedback_tag_name or "feedback"
            feedback_regex = f"^{default_tag}$"

        tries = 0
        while True:
            tries += 1
            try:
                for convo in self.client.conversations.find_all():
                    self.logger.info("Processing convo")

                    self.sleep_if_rate_limit()
                    if convo.updated_at < cutoff:
                        break
                    real_convo = self.client.conversations.find(id=convo.id)
                    self.sleep_if_rate_limit()
                    tags = real_convo.tags
                    for tag in tags:
                        feature_request_match = feature_request_regex.match(tag.name)
                        feedback_match = feedback_regex.match(tag.name)

                        self.logger.info(f"Tag: {tag.name}")
                        self.logger.info(f"Feedback regex match: {feedback_match}")
                        self.logger.info(
                            f"Feature request regex match: {feature_request_match}"
                        )

                        fr = None
                        state = Feedback.ACTIVE
                        if feature_request_match:
                            state = Feedback.ARCHIVED
                            defaults = {
                                "import_token": import_token,
                            }
                            fr, created = FeatureRequest.objects.get_or_create(
                                customer=self.customer,
                                title=feature_request_match.group(
                                    "feature_request_name"
                                ),
                                defaults=defaults,
                            )
                            self.logger.info(
                                f"Processed feature request: {fr.title} - created: {created}"
                            )

                        if feature_request_match or feedback_match:
                            self.logger.info("Processing feedback")
                            contact = self.client.contacts.find(
                                id=real_convo.contacts[0].id
                            )
                            app_user = AppUser.objects.get_best_match_user(
                                self.customer,
                                contact.email,
                                contact.id,
                                contact.external_id,
                            )

                            self.logger.info(f"AppUser is: {app_user}")

                            defaults = {
                                "user": app_user,
                                "source_updated": convo.updated_at,
                                "source_created": convo.created_at,
                                "source_url": self.get_source_url(convo, workspace_id),
                                "source_username": "Savio Intercom Import",
                                "feature_request": fr,
                                "state": state,
                                "import_token": import_token,
                            }

                            obj, created = Feedback.objects.update_or_create(
                                customer=self.customer,
                                problem=self.get_full_message(real_convo),
                                defaults=defaults,
                            )
                            self.logger.info(
                                f"Finished processiong feedback. Created? {created}"
                            )
                break
            except requests.exceptions.ReadTimeout:
                self.logger.info("Got ReadTimeout.")
                if tries <= self.MAX_RETRIES:
                    self.logger.info(f"Retrying ({tries}) in {self.RETRY_COOL_OFF}")
                    sleep(self.RETRY_COOL_OFF)
                    continue
                else:
                    raise
