import hmac
import json
from base64 import standard_b64decode
from django.http import HttpResponse
from django.conf import settings
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .models import Event

@csrf_exempt
def receive_segment_webhook(request):
    if request.method == 'POST':
        try:
            VALID_TYPES = (
                'track',
            )

            json_data = json.loads(request.body)

            signature = request.META.get('HTTP_X_SIGNATURE', '')
            digest = hmac.new(
                settings.SEGMENT_WEBHOOK_SHARED_SECRET.encode('utf-8'),
                request.body, 'sha1').hexdigest()
            if signature != digest:
                return HttpResponse("Invalid signature", status=401)
            if json_data['type'] not in VALID_TYPES:
                return HttpResponse(status=200)

            Event.objects.create(data=json_data)
        except json.JSONDecodeError:
            return HttpResponse("Invalid JSON", status=400)
        return HttpResponse(status=200)
    else:
        return HttpResponse("Only POST accepted", status=400)

