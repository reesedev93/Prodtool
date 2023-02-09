from django.apps import AppConfig
from django.conf import settings
import analytics as segment

def on_error(error, items):
    print("Segment error:", error)

class InternalAnalyticsConfig(AppConfig):
    name = 'internal_analytics'

    def ready(self):
        segment.write_key = settings.SEGMENT_WRITE_KEY
        segment.debug = settings.DEBUG
        segment.send = settings.PRODUCTION
        if not settings.PRODUCTION:
            segment.on_error = on_error
