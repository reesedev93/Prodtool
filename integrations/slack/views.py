import datetime
import hmac
import json
import logging
import time

import requests
from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.template.defaultfilters import truncatechars
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DeleteView
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from sentry_sdk import capture_message

from accounts.decorators import role_required
from accounts.models import OnboardingTask, User
from appaccounts.models import AppUser
from feedback.models import FeatureRequest, Feedback
from internal_analytics import tracking

from .forms import SlackChooseChannelForm
from .models import SlackSettings
from .utils import (
    delete_ephemeral_message,
    get_dialog_json,
    get_slack_hmac,
    validate_slack_request,
)


class RequestContextMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if hasattr(self, "request"):
            kwargs.update({"request": self.request})
        return kwargs


class ReturnUrlMixin(RequestContextMixin):
    def get_return_url(self):
        raise NotImplementedError()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["return"] = self.get_return_url()
        return context


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class SlackSettingsDeleteItemView(ReturnUrlMixin, DeleteView):
    model = SlackSettings
    template_name = "generic_confirm_delete.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["type"] = "Slack Integration"
        context["name"] = "your Slack integration?"
        return context

    def get_queryset(self):
        return SlackSettings.objects.filter(
            pk=self.request.user.customer.slack_settings.id
        )

    def get_return_url(self):
        return_url = reverse_lazy("accounts-integration-settings-list")
        return self.request.GET.get("return", return_url)

    def get_success_url(self):
        return self.get_return_url()

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, "Slack integration disabled")
        return super(SlackSettingsDeleteItemView, self).delete(request, *args, **kwargs)


@role_required(User.ROLE_OWNER_OR_ADMIN)
def slack(request):
    try:
        slack_settings = SlackSettings.objects.get(customer_id=request.user.customer.id)
        already_installed = True
    except SlackSettings.DoesNotExist:
        slack_settings = None
        already_installed = False

    context = {
        "slack_settings": slack_settings,
        "already_installed": already_installed,
        "host": settings.HOST,
        "slack_client_id": settings.SLACK_CLIENT_ID,
    }

    return render(request, "slack/install.html", context)


@role_required(User.ROLE_OWNER_OR_ADMIN)
def slack_success(request):
    return render(request, "slack/success.html")


@role_required(User.ROLE_OWNER_OR_ADMIN)
def slack_oauth_callback(request):
    auth_url = "https://slack.com/api/oauth.access"
    data = {
        "code": request.GET.get("code"),
        "client_id": settings.SLACK_CLIENT_ID,
        "client_secret": settings.SLACK_CLIENT_SECRET,
        "redirect_uri": settings.HOST + reverse("integrations-slack-oauth-callback"),
    }
    response = requests.post(auth_url, data)

    if response.ok:
        if request.GET.get("state") == "needs_auth":

            # Check to ensure that Slack is not connected to another Savio vault.  If it is,
            # Show an error
            slack_settings = SlackSettings.objects.filter(
                slack_team_id=response.json()["team_id"]
            )
            if slack_settings.count() > 0:
                messages.error(
                    request,
                    "This Slack workspace is already connected to another Savio Vault. Email help@savio.io if you have questions.",
                )
                return redirect("integrations-slack")
            else:
                slack_settings = SlackSettings.objects.create(
                    customer_id=request.user.customer.id
                )

            # If "bot" is in the response, we've been sent here from Slack.
            # If it's not, we probably got here by hitting the back button
            # so we'll skip this section and redirect to the choose channel page
            if "bot" in response.json():
                slack_settings.slack_bot_token = response.json()["bot"][
                    "bot_access_token"
                ]
                slack_settings.slack_bot_user_id = response.json()["bot"]["bot_user_id"]
                slack_settings.slack_team_name = response.json()["team_name"]
                slack_settings.slack_team_id = response.json()["team_id"]
                slack_settings.slack_user_id = response.json()["user_id"]
                slack_settings.slack_user_access_token = response.json()["access_token"]
                slack_settings.user_id = request.user.id
                slack_settings.save()

                tracking.integration_connected(
                    request.user, tracking.EVENT_SOURCE_SLACK
                )

            OnboardingTask.objects.filter(
                customer=request.user.customer,
                task_type=OnboardingTask.TASK_CONNECT_HELP_DESK,
            ).update(completed=True, updated=timezone.now())

            return redirect("integrations-slack-choose-channel")
        else:
            # error, invalid request.
            messages.error(
                request, "There was an error installing Slack.  Please try again."
            )
            return redirect("integrations-slack")

    else:
        # error, invalid request.
        messages.error(
            request, "There was an error installing Slack.  Please try again."
        )
        return redirect("integrations-slack")


@role_required(User.ROLE_OWNER_OR_ADMIN)
def slack_choose_channel(request):
    if request.method == "POST":
        form = SlackChooseChannelForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            return redirect("integrations-slack-success")
    else:

        # GET below this line
        form = SlackChooseChannelForm(user=request.user)

        return render(request, "slack/choose-channel.html", {"form": form})


@csrf_exempt
@api_view(
    ["POST",]
)
def slack_dialog(request):  # noqa: C901

    json_payload, slack_settings = validate_slack_request(request)

    # An error occured in validate_slack_response.  So we return a 200
    # and tell Slack to not retry.
    if slack_settings is None:
        response = HttpResponse(status=200)
        response["X-Slack-No-Retry"] = "1"
        return response

    customer = slack_settings.customer

    channel_id = json_payload["channel"]["id"]
    payload_type = json_payload["type"]

    headers = {"Content-Type": "application/json; charset=utf-8"}

    if payload_type == "block_actions":
        # Yes or No button has been clicked

        if json_payload["actions"][0]["text"]["text"] == "No":
            # "No" Button clicked - delete ephemeral message
            delete_ephemeral_message(
                json_payload["container"]["message_ts"],
                json_payload["response_url"],
                headers,
            )

        else:
            # "Yes" button clicked - show dialog

            trigger_id = json_payload["trigger_id"]

            # message_ts is the pointer to the message we care about adding to Savio, NOT the timestamp
            # of the response to the Yes/No ephemeral message that just got POSTed
            message_ts = json_payload["actions"][0]["value"]

            # Get Message so we can display "problem" as a default in the Dialog's problem textarea
            message_url = "https://slack.com/api/channels.history"
            message_json = {
                "oldest": message_ts,
                "count": 1,
                "inclusive": True,
                "channel": channel_id,
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded;",
                "Authorization": "Bearer " + slack_settings.slack_user_access_token,
            }
            response = requests.post(message_url, data=message_json, headers=headers)

            if not response.json()["ok"]:
                capture_message(
                    f"Error getting Slack Message: message.json: {response.json()}. slack_settings_id: {slack_settings.id}."
                )
                response = HttpResponse(status=200)
                response["X-Slack-No-Retry"] = "1"
                return response
            else:
                message = response.json()["messages"][0]["text"]

            dialog_json = get_dialog_json(
                trigger_id, "show_create_feedback_dialog", message_ts, message, customer
            )

            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": "Bearer " + slack_settings.slack_bot_token,
            }

            dialog_url = "https://slack.com/api/dialog.open"
            response = requests.post(
                dialog_url, data=json.dumps(dialog_json), headers=headers
            )

            if not response.json()["ok"]:
                capture_message(
                    f"Error generating Slack dialog: response.json: {response.json()}. message: {message}. message_ts: {message_ts}. slack_settings_id: {slack_settings.id}"
                )
                response = HttpResponse(status=200)
                response["X-Slack-No-Retry"] = "1"
                return response

            delete_ephemeral_message(
                json_payload["container"]["message_ts"],
                json_payload["response_url"],
                headers,
            )

    else:
        # Dialog initiated by message action
        callback_id = json_payload["callback_id"]

        if callback_id == "show_create_feedback_dialog":
            if payload_type == "dialog_submission":

                # Saving a Posted Dialog

                slack_user_name = json_payload["user"]["name"]
                slack_user_id = json_payload["user"]["id"]
                problem = json_payload["submission"]["problem"]
                person = json_payload["submission"]["person"]
                new_person_email = json_payload["submission"]["new_person_email"]
                feedback_from = json_payload["submission"]["feedback_from"]
                feature_request = json_payload["submission"]["feature_request"]
                response_url = json_payload["response_url"]

                # Validate submitted data
                errors = {"errors": []}
                if not problem:
                    errors["errors"].append(
                        {
                            "name": "problem",
                            "error": "Can't be blank. Please try again.",
                        }
                    )

                if not feedback_from:
                    errors["errors"].append(
                        {
                            "name": "feedback_from",
                            "error": "Can't be blank. Please try again.",
                        }
                    )

                if not (person or new_person_email):

                    errors["errors"].append(
                        {
                            "name": "person",
                            "error": "You need to select an existing or new person.",
                        }
                    )
                    errors["errors"].append(
                        {
                            "name": "new_person_email",
                            "error": "You need to select an existing or new person.",
                        }
                    )

                if len(errors["errors"]) > 0:
                    capture_message(
                        f"Invalid params submitted from Slack. problem: {problem}. person: {person}. feedback_from: {feedback_from}"
                    )
                    return JsonResponse(errors)

                # To post to the Slack channel, we first need to get the permalink of the parent message.
                permalink_url = "https://slack.com/api/chat.getPermalink"
                shared_ts = json_payload["state"]

                # Add Auth header to headers. We don't need it for previous posts to response_url, but we do
                # post web API methods like chat.getPermalink
                headers["Authorization"] = "Bearer " + slack_settings.slack_bot_token

                permalink_params = {"channel": channel_id, "message_ts": shared_ts}
                permalink_response = requests.post(
                    permalink_url, params=permalink_params, headers=headers
                ).json()

                if not permalink_response["ok"]:

                    params = {
                        "text": "There was an error saving your feedback.  Please try again.",
                    }
                    requests.post(
                        response_url, data=json.dumps(params), headers=headers
                    )

                    capture_message(
                        f"Invalid permalink from Slack. channel: {channel_id}. message timestamp: {shared_ts}. "
                    )
                    return HttpResponse(status=406)

                message_permalink = permalink_response["permalink"]

                # Look up User. The user in Slack likely won't have a row in our users table.
                if slack_settings.slack_user_id == slack_user_id:
                    u = slack_settings.user
                else:
                    u = None

                # Are we creating a new person, or using an existing one?  Figure it out.
                if person:
                    use_person_id = person
                else:
                    # handle case where email entered but user exists.
                    try:
                        user = AppUser.objects.get(
                            email=new_person_email, customer_id=customer.id
                        )
                    except AppUser.DoesNotExist:
                        user = AppUser.objects.create(
                            email=new_person_email, customer_id=customer.id
                        )

                    use_person_id = user.id

                # Save feedback to DB
                feedback = Feedback(
                    customer=customer,
                    source_url=message_permalink,
                    problem=problem,
                    feedback_type=feedback_from,
                    feature_request_id=feature_request,
                    user_id=use_person_id,
                    source_username=slack_user_name,
                    created_by=u,
                )
                feedback.save()

                if u:
                    user_id = u.id
                else:
                    user_id = f"Slack - {slack_user_id}"

                tracking.feedback_created(
                    user_id, customer, feedback, tracking.EVENT_SOURCE_SLACK
                )

                # Then, we'll post a reply to the message as part of a thread
                post_message_url = "https://slack.com/api/chat.postMessage"

                now = datetime.datetime.now()
                unix_time = now.timestamp()

                savio_feedback_url = settings.HOST + feedback.get_absolute_url()

                date_string = (
                    "<!date^"
                    + repr(int(unix_time))
                    + "^{date} at {time}^"
                    + savio_feedback_url
                    + "|"
                    + now.strftime("%b %d %Y at %I:%M %p")
                    + ">"
                )

                company_str = ""
                if feedback.user.company:
                    company_str = f" @ {feedback.user.company.name}"

                fr_string = "None"
                if feedback.feature_request is not None:
                    fr_url = settings.HOST + reverse(
                        "feature-request-feedback-details",
                        kwargs={"pk": feedback.feature_request.id},
                    )
                    fr_string = f"<{fr_url}|{feedback.feature_request.title}>"

                # This Code creates a payload to reply in a thread with the original message as the parent
                reply_json = {
                    "channel": channel_id,
                    "as_user": False,
                    "link_names": True,
                    "mrkdwn": True,
                    "unfurl_links": True,
                    "thread_ts": shared_ts,
                    "blocks": [
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"@{slack_user_name} pushed this customer feedback to Savio on {date_string}:",
                                },
                            ],
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*From*\n{feedback.user.get_name_or_email()}{company_str} ({dict(feedback.TYPE_CHOICES)[feedback.feedback_type]})\n\n*Feedback*\n{problem}\n\n*Feature Request*\n{fr_string}",
                            },
                        },
                    ],
                }
                # End Code posts a response to the Slack Channel with the message posted to Savio

                response = requests.post(
                    post_message_url, data=json.dumps(reply_json), headers=headers
                )

            elif payload_type == "message_action":

                # Show a Dialog
                trigger_id = json_payload["trigger_id"]
                message = json_payload["message"]["text"]
                message_ts = json_payload["message_ts"]

                dialog_json = get_dialog_json(
                    trigger_id, callback_id, message_ts, message, customer
                )

                headers = {
                    "Content-Type": "application/json; charset=utf-8",
                    "Authorization": "Bearer " + slack_settings.slack_bot_token,
                }

                dialog_url = "https://slack.com/api/dialog.open"
                response = requests.post(
                    dialog_url, data=json.dumps(dialog_json), headers=headers
                )

    return Response(status=status.HTTP_200_OK)


@csrf_exempt
@api_view(
    ["POST",]
)
def slack_typeahead(request):
    logger = logging.getLogger(__name__)
    logger.error("---------------- Begin slack_typeahead -------------- ")

    start_time = time.time()

    results = {"options": []}

    json_payload, slack_settings = validate_slack_request(request)
    customer = slack_settings.customer

    search_type = json_payload["name"]
    search_val = json_payload["value"]

    logger.error(
        f"customer: {customer.name} ({customer.id}) search_type: {search_type} search_val: {search_val}"
    )

    # NB: Slack dynamic lists can't have items longer than 75 chars or you just get
    # a spinning gears icon when you search.
    if search_type == "person":
        app_users = AppUser.objects.filter(customer=customer)
        app_users = app_users.filter(
            Q(name__icontains=search_val) | Q(email__icontains=search_val)
        )[:100]

        for user in app_users:
            option = {
                "label": truncatechars(user.get_friendly_name_email_and_company(), 75),
                "value": user.id,
            }
            results["options"].append(option)

        logger.error(f"total results: {len(results['options'])}")

    elif search_type == "feature_request":
        frs = FeatureRequest.objects.filter(
            customer=customer, title__icontains=search_val
        )[:100]

        for fr in frs:
            option = {"label": truncatechars(fr.title, 75), "value": fr.id}
            results["options"].append(option)
    else:
        capture_message(
            f"Invalid search type sent to slack_typeahead. Search type: {search_type}"
        )

    response = JsonResponse(results)

    logger.error(f"Total execution time {time.time() - start_time} seconds")
    logger.error("---------------- End slack_typeahead -------------- ")

    return response


@csrf_exempt
@api_view(
    ["POST",]
)
def slack_webhook(request):
    logger = logging.getLogger(__name__)
    logger.error("---------------- Slack Webhook -------------- ")

    logger.error(f"---------------- request.META: {request.META} -------------- ")

    # Get HMAC from request
    timestamp, hmac_digest = get_slack_hmac(request)
    slack_signature = request.META["HTTP_X_SLACK_SIGNATURE"]

    # The request timestamp is more than ten seconds from local time.
    # If so, we ignore it.
    occurred_in_last_10s = (
        int(datetime.datetime.now().timestamp()) - int(timestamp)
    ) < 10

    # If signatures don't match, or request occurred more than 5 minutes ago, discard request
    if not (hmac.compare_digest(slack_signature, hmac_digest) and occurred_in_last_10s):
        logger.error(f"slack_signature: {slack_signature}")
        logger.error(f"hmac_digest: {hmac_digest}")
        logger.error(f"occurred_in_last_10s: {occurred_in_last_10s}")
        capture_message(
            f"Old webhook or Invalid signature from Slack: discarding.  request.body: {request.body}. slack_sig: {slack_signature}. computed_sig: {hmac_digest}. occurred_in_last_10s: {occurred_in_last_10s}."
        )
        return HttpResponse(status=200)  # Return a 200 so Slack doesn't keep retrying

    logger.error("---------------- After invalid signature guard -------------- ")

    # Slack needs to verify the URL and does so by sending a "challenge" param when we set the URL in their
    # GUI here: https://api.slack.com/apps/AHB04HNE9/event-subscriptions
    # A payload with "challenge" is only sent when we set a new webhook URL
    if "challenge" in request.data:
        return JsonResponse({"challenge": request.data["challenge"]})

    logger.error("---------------- After challenge guard -------------- ")

    # Handle app_uninstalled webhooks

    if request.data["event"]["type"] == "app_uninstalled":
        team_id = request.data["team_id"]
        try:
            # TODO: pretty sure we have a bug here. If you have multiple installs
            # for the same team it's going to generate a MutipleObjects exception.
            # We should probably just being doing filter(slack_team_id=team_id).delete().
            # Don't have time to dig in on that right now.
            slack_settings = SlackSettings.objects.get(slack_team_id=team_id)
        except SlackSettings.DoesNotExist:
            return HttpResponse(status=200)

        logger.error("---------------- Uninstalled Slack app -------------- ")

        tracking.integration_disconnected(
            slack_settings.user, tracking.EVENT_SOURCE_SLACK
        )
        slack_settings.delete()

        return HttpResponse(status=200)

    logger.error("---------------- After uninstall webhook guard -------------- ")

    channel_id = request.data["event"]["channel"]
    team_id = request.data["team_id"]

    # This section responds to a DM to SavioBot
    if request.data["event"]["channel_type"] == "im":

        # Ignore all requests with a bot_id in them - we don't want to respond to ourself!
        if "bot_id" in request.data["event"]:
            return HttpResponse(status=200)

        # This is a DM, so get the customer by team_id.
        try:
            slack_settings = SlackSettings.objects.get(
                slack_team_id=team_id, slack_feedback_channel_id=channel_id
            )
        except SlackSettings.DoesNotExist:
            return HttpResponse(status=406)

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": "Bearer " + slack_settings.slack_bot_token,
        }
        msg_url = "https://slack.com/api/chat.postMessage"

        if request.data["event"]["text"] == "help":
            text = "I help you send customer feedback posted in Slack to Savio.\n\n"
            text = (
                text
                + f"There are two ways to use Savio:\n\n1. Post customer feedback to the #{slack_settings.slack_feedback_channel_name} channel and I'll ask you if you want to send it to Savio. <https://www.youtube.com/watch?v=KOwnybk_clU|Watch a 30 second video.>"
            )
            text = (
                text
                + "\n2. Click the three dots to the right of any Slack message and choose 'Push to Savio'.  <http://www.youtube.com/watch?v=DY7Ci5kUVG8|Watch a 30 second video.>"
            )
            msg_json = {
                "channel": channel_id,
                "text": text,
                "link_names": True,
                "unfurl_media": False,
            }
        elif request.data["event"]["text"] == "power":
            text = f"Send feedback to Savio faster when you post Slack messages to #{slack_settings.slack_feedback_channel_name} by using this format:\n"
            text = (
                text
                + "1. `customer_email@example.com: Some feedback from your customer` OR \n2. `Customer Name: Some feedback from your customer`"
            )
            text = (
                text
                + f"\n\nWhen you use this format, we'll populate the Person dropdown with that person if they've been imported into Savio.\n\nWatch it in action: {settings.HOST}/static/images/help/slack-power-user.gif"
            )
            msg_json = {
                "channel": channel_id,
                "text": text,
                "link_names": True,
                "unfurl_link": True,
                "unfurl_media": True,
            }
        else:
            msg_json = {
                "channel": channel_id,
                "text": "Sorry, I don't understand that. Please type 'help' or 'power' if you're a power user.",
            }

        requests.post(msg_url, data=json.dumps(msg_json), headers=headers)

    elif "user" in request.data["event"]:

        logger.error(
            "---------------- Not a DM, is Savio listing to channel? -------------- "
        )

        # This is not a DM, so get the customer by channel_id to see if we care about messages posted to this channel.
        if request.data["event"]["type"] == "message":
            try:
                slack_settings = SlackSettings.objects.get(
                    slack_team_id=team_id, slack_feedback_channel_id=channel_id
                )
            except SlackSettings.DoesNotExist:
                logger.error(
                    f"---------------- Slack Settings does not exist for team_id {team_id} and slack_feedback_channel_id {channel_id}, returning 200 -------------- "
                )
                return HttpResponse(status=200)

        logger.error(
            f"---------------- Message is user initiated. Slack_settings: {slack_settings} -------------- "
        )

        # We have a user, which means this is a user-initiated message
        user_id = request.data["event"]["user"]

        logger.error(
            f"---------------- user_id == slack_settings.slack_bot_user_id: {user_id == slack_settings.slack_bot_user_id} -------------- "
        )
        logger.error(f"---------------- request.data: {request.data} -------------- ")

        # Don't respond with ephemeral msg if user is Slack bot or if msg is
        # part of a thread or if there's a message subtype - we don't care about those.
        if (
            not (user_id == slack_settings.slack_bot_user_id)
            and ("thread_ts" not in request.data["event"])
            and ("subtype" not in request.data["event"])
        ):

            logger.error(
                "---------------- Inside Guard. Should return ephemeral message -------------- "
            )

            message_ts = request.data["event"]["ts"]

            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": "Bearer " + slack_settings.slack_bot_token,
            }
            msg_url = "https://slack.com/api/chat.postEphemeral"

            msg_json = {
                "channel": channel_id,
                "user": user_id,
                "as_user": False,
                "text": "",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "Is this customer feedback that you want to send to Savio?",
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Yes"},
                                "value": message_ts,
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "No"},
                                "value": "No",
                            },
                        ],
                    },
                ],
            }

            requests.post(msg_url, data=json.dumps(msg_json), headers=headers)
        else:
            logger.error(
                "---------------- NOT inside Guard. NOT returning ephemeral message -------------- "
            )

    return Response(status=status.HTTP_200_OK)
