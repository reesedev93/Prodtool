import json

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from accounts.tasks import (
    send_admin_subscription_summary_email,
    sync_feedback_counts_and_mrr_with_stripe,
)
from feedback.models import CustomerFeedbackImporterSettings
from feedback.tasks import import_feedback, send_status_emails, unsnooze_feedback
from marketingmonitor.tasks import monitor_hn


@csrf_exempt
def run_task(request):
    # To be used in conjunction with a Cloudwatch event rule and a
    # lambda function (see comment code below).
    # The lambda function it's this view and the view runs the
    # corresponding celery task. It needs to happen quick otherwise
    # the lambda function will time out (10s).
    # The secret ensures that we aren't running something we shouldn't
    try:
        task_json = json.loads(request.body)
        print(task_json)
        if task_json["secret"] != settings.CLOUDWATCH_EVENT_SECRET:
            return HttpResponse(status=401)

        task_name = task_json["task_name"]
        if task_name == "run_feedback_importers":
            for cfis in CustomerFeedbackImporterSettings.objects.all():
                import_feedback.delay(cfis.pk, None)
        elif task_name == "unsnooze_feedback":
            unsnooze_feedback.delay()
        elif task_name == "send_status_emails":
            send_status_emails.delay()
        elif task_name == "sync_feedback_counts_and_mrr_with_stripe":
            sync_feedback_counts_and_mrr_with_stripe.delay()
        elif task_name == "send_admin_subscription_summary_email":
            send_admin_subscription_summary_email.delay()
        elif task_name == "monitor_hn":
            monitor_hn.delay()
        else:
            raise Exception(f"Invalid task name {task_name}")
        return HttpResponse(status=204)
    except (json.JSONDecodeError, KeyError):
        return HttpResponse(status=401)


# This is code for the lambda function that the Cloudwatch event
# rule will trigger.
# The assumption is that you create a Cloudwatch Event Rule with
# a type of Constant (JSON Text) with a value
# like: '{"task_name": "run_feedback_importers"}'
# You also need to setup two env vars for the lambda:
# 1. RUN_TASK_URL - the url to hit
# 2. SECRET - the secret that will get validated in the view.
# It needs to match the value you've set up your Django settings file.
#
# ACTUAL CODE FOR LAMBDA HERE:
#
# import os
# from datetime import datetime
# from urllib import request
# import json

# RUN_TASK_URL = os.environ['RUN_TASK_URL']  # URL to post to
# SECRET = os.environ['SECRET']  # How to prove it's not some rando


# def lambda_handler(event, context):
#     # Assumes Cloudwatch event is of type Constant (JSON Text) with a value
#     # like: '{"task_name": "run_feedback_importers"}'
#     print('Executing run task for endpoint {} with cloudwatch event json {} at {}...'.format(RUN_TASK_URL, event, datetime.now()))
#     try:
#         payload = {
#             'secret': SECRET,
#             'task_name': event['task_name'],
#         }

#         req = request.Request(RUN_TASK_URL, data=bytes(json.dumps(payload), encoding='utf-8'))
#         req.add_header('Content-Type', 'application/json')
#         response = request.urlopen(req)
#         if response.getcode() != 204:
#             raise Exception('run task failed')
#     except:
#         print('Run task failed!')
#         raise
#     else:
#         print('Run task worked!')
#     finally:
#         print('Run task executed at {}'.format(str(datetime.now())))
