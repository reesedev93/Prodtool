import json
from base64 import standard_b64decode
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from feedback.models import CustomerFeedbackImporterSettings

@csrf_exempt
def receive_segment_webhook(request):
    if request.method == 'POST':
        try:
            VALID_TYPES = (
                'identify',
                'group',
                'delete',
            )

            json_data = json.loads(request.body)
            # They give us a string like:
            # f"Basic {base64.standard_b64encode('SECRET:')}""
            # 1. Prepend 'Basic '
            # 2. Base64 encode our secret + a ':' and a blank password

            # Get secret from header
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            secret = auth_header[len('Basic '):]
            secret = standard_b64decode(secret.encode('utf-8')).decode('utf-8')
            secret = secret.rstrip(':')

            cfis = CustomerFeedbackImporterSettings.objects.get(
                importer__name="Segment",
                webhook_secret=secret)

            if json_data['type'] not in VALID_TYPES:
                # return HttpResponse(status=501)
                # Per spec this should return a 501
                # The issue with that is two fold:
                # 1. You can't configure things on their end
                # to only send types you what you want so
                # they send them all anyway and the customer
                # sees a bunch of errors in the Segment monitoring
                # tool.
                # 2. Because we are constantly generating 501s
                # Elastic Beanstalk thinks our env is sick and
                # sends out a stream of warning emails.
                # So given those to issues just send 200 until
                # Segment lets us configure out integraiton in a
                # way where they only send us the types we want.
                return HttpResponse(status=200)

            cfis.handle_webhook(json_data)
        except CustomerFeedbackImporterSettings.DoesNotExist:
            return HttpResponse(status=401)
        except json.JSONDecodeError:
            return HttpResponse("Invalid JSON", status=400)
        return HttpResponse(status=200)
    else:
        return HttpResponse("Only POST accepted", status=400)
