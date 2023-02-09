from django.conf import settings
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from feedback.models import CustomerFeedbackImporterSettings
from .api import Client

@receiver(pre_delete, sender=CustomerFeedbackImporterSettings)
def remove_webhooks(sender, instance, **kwargs):
  if instance.importer.name == "Help Scout":
    client = Client(instance.api_key, instance.refresh_token, settings.HELPSCOUT_CLIENT_ID, settings.HELPSCOUT_CLIENT_SECRET, instance.save_refreshed_tokens)
    client.delete_our_webhooks()
