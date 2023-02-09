import datetime
import hashlib
import hmac
import json

import requests
from django.conf import settings
from django.db.models import Q
from sentry_sdk import capture_exception, capture_message, configure_scope

from appaccounts.models import AppUser
from feedback.models import FeedbackTemplate

from .models import SlackSettings


def get_slack_hmac(request):
    version = "v0"
    timestamp = request.META["HTTP_X_SLACK_REQUEST_TIMESTAMP"]
    body = request.body.decode("utf-8")
    sig_basestring = version + ":" + timestamp + ":" + body

    hmac_digest = (
        "v0="
        + hmac.new(
            key=settings.SLACK_SIGNING_SECRET.encode("ascii"),
            msg=sig_basestring.encode("ascii"),
            digestmod=hashlib.sha256,
        ).hexdigest()
    )
    return timestamp, hmac_digest


def get_dialog_json(trigger_id, callback_id, message_ts, message, customer):
    selected_user = {}
    search_string = None
    problem = message

    # This checks to see if we have a colon.  If we do, we look up app_users by the string to the left
    # of the colon.  E.g. if the message is "John Doe: I have some problem" we look up app users by
    # "John Doe".  If it's "jon@doe.com: I have a problem", we'll look up app users by jon@doe.com.
    # If we find an app user, we'll also remove that string and the colon from the problem.  So in both
    # of the above cases the problem we'd send back in the dialog would be "I have a problem"
    items = message.split(":")
    if len(items) > 1:
        # there is a colon in the message.  Now we need to see if the string begins with a mailto link
        # because then we know for sure that the first string was entered as an email address and Slack
        # smart formatted it as
        # '<mailto:foo@bar.com|foo@bar.com>: some_problem' so we need to strip out email and problem.

        if message.find("<mailto:") == 0:
            # the string definitely begins with an email address.
            # e.g. '<mailto:foo@bar.com|foo@bar.com>: some_problem'
            # so let's strip out email and problem.

            # we split 'foo@bar.com|foo@bar.com>' into two strings with the pipe as the delimiter and
            # take the first element as the search term:
            search_string = items[1].split("|")[0]

            # from '<mailto:foo@bar.com|foo@bar.com>: some_problem' we take the third item as split
            # by the colon and set it as the problem
            if len(items) > 2:
                problem = items[2].strip()
            else:
                problem = ""
        else:
            # there is a colon in the string,
            # e.g. 'Joe Smith: some problem".  So we use the item to the left of the colon as the search string
            search_string = items[0]

            # Then we set the item to the right of the colon as the problem.
            problem = items[1].strip()

    try:
        # If the user has setup a Feedback Template plug the problem into it.
        # We assume the template is something like:
        # Step1:
        #
        # Step2:
        #
        # and if they are passing text to us it belong in "Step1".
        #
        # This may turn to be a bad assumption but it's annoying
        # to have to take the text we are passing in from the Slack
        # messasge and be forced to move it around right off the hop.
        feedback_template = FeedbackTemplate.objects.get(customer=customer)
        template_parts = feedback_template.template.split("\n")
        template_parts.insert(1, problem)
        problem = "\n".join(template_parts)
    except FeedbackTemplate.DoesNotExist:
        pass

    json = {
        "trigger_id": trigger_id,
        "dialog": {
            "callback_id": callback_id,
            "title": "Add Customer Feedback",
            "submit_label": "Save",
            "notify_on_cancel": False,
            "state": message_ts,
            "elements": [
                {
                    "type": "textarea",
                    "label": "Customer Problem",
                    "name": "problem",
                    "value": problem,
                    "placeholder": "The problem this customer has is...",
                    "hint": "Include verbatim quote from customer if possible",
                },
                {
                    "type": "select",
                    "label": "Choose an existing Person",
                    "data_source": "external",
                    "min_query_length": 2,
                    "name": "person",
                    "placeholder": "Who provided this feedback?",
                    "optional": True,
                    "hint": "You must choose an existing or new person",
                },
                {
                    "label": "Or add a new one",
                    "name": "new_person_email",
                    "type": "text",
                    "placeholder": "Email of person who provided feedback",
                    "optional": True,
                },
                {
                    "type": "select",
                    "label": "Feedback From",
                    "data_source": "static",
                    "placeholder": "This person is a...",
                    "name": "feedback_from",
                    "options": [
                        {"label": "Active customer", "value": "ACTIVE"},
                        {"label": "Churned customer", "value": "CHURNED"},
                        {"label": "Internal user", "value": "INTERNAL"},
                        {"label": "Lost deal", "value": "LOST DEAL"},
                        {"label": "Prospect", "value": "PROSPECT"},
                        {"label": "Other", "value": "OTHER"},
                    ],
                },
                {
                    "type": "select",
                    "label": "Feature Request",
                    "name": "feature_request",
                    "optional": True,
                    "placeholder": "Search for a feature request...",
                    "data_source": "external",
                    "min_query_length": 2,
                },
            ],
        },
    }

    # If there's an app user found, select it by default.
    if search_string:
        app_user = AppUser.objects.filter(customer=customer).filter(
            Q(name__icontains=search_string) | Q(email__icontains=search_string)
        )
        if len(app_user) == 1:
            selected_user = {
                "label": app_user.first().get_friendly_name_email_and_company(),
                "value": app_user.first().id,
            }
            json["dialog"]["elements"][1]["selected_options"] = [selected_user]

    return json


def delete_ephemeral_message(ts, response_url, headers):
    response_json = {"ts": ts, "delete_original": True}
    response_url = response_url
    requests.post(response_url, data=json.dumps(response_json), headers=headers)


def validate_slack_request(request):
    # START Validate Request.  This section validates that the request is coming from Slack and is
    # Legitimate.  Specifically it looks for:
    # 1. Whether the request's computed signature matches the header Slack sends.
    #    See https://api.slack.com/docs/verifying-requests-from-slack for more info.
    #
    # 2. Whether the request occurred in the last 10 seconds (to prevent against replay attack).
    #
    # If the requests don't match or the request occurred more than 10 seconds ago, we discard it and return an error
    #
    timestamp, hmac_digest = get_slack_hmac(request)
    slack_signature = request.META["HTTP_X_SLACK_SIGNATURE"]

    json_payload = json.loads(request.data["payload"])
    channel_id = json_payload["channel"]["id"]
    team_id = json_payload["team"]["id"]

    # Set scope that gets passed to Sentry if there's an error
    with configure_scope() as scope:
        scope.set_extra("team_id", team_id)
        scope.set_extra("channel_id", channel_id)
        scope.set_extra("json_payload", json_payload)

    headers = {"Content-Type": "application/json; charset=utf-8"}

    try:
        slack_settings = SlackSettings.objects.get(slack_team_id=team_id)
    except SlackSettings.DoesNotExist as e:
        response_url = json_payload["response_url"]
        params = {
            "text": "Please install the Slack integration: https://www.savio.io/app/accounts/integration-settings",
        }
        capture_exception(e)
        requests.post(response_url, data=json.dumps(params), headers=headers)
        return {}, None

    # The request timestamp is more than 10 seconds from local time.
    # If so, we assume it's a replay attack, so we'll ignore the request.
    occurred_in_last_10s = (
        int(datetime.datetime.now().timestamp()) - int(timestamp)
    ) < 10

    # If signatures don't match, or request occurred more than 10 seconds ago, discard request
    if not (hmac.compare_digest(slack_signature, hmac_digest) and occurred_in_last_10s):
        response_url = json_payload["response_url"]
        params = {
            "text": "There was an error with your request. Please try again.",
        }
        capture_message(
            f"Invalid signature from Slack or possible replay attack. slack_sig: {slack_signature}. computed_sig: {hmac_digest}. occurred_in_last_10s: {occurred_in_last_10s}."
        )
        requests.post(response_url, data=json.dumps(params), headers=headers)
        return {}, None

    return json_payload, slack_settings
