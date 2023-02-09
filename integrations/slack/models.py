from django.db import models
from accounts.models import Customer, User

class SlackSettingsManager(models.Manager):
    def has_slack_settings(self, customer):
        try:
            customer.slack_settings
            return True
        except SlackSettings.DoesNotExist:
            return False


class SlackSettings(models.Model):
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE,related_name="slack_settings")
    user = models.OneToOneField(User, null=True, on_delete=models.SET_NULL)

    # From Customer
    slack_bot_user_id = models.CharField(max_length=255, blank=True)
    slack_bot_token = models.CharField(max_length=255, blank=True)
    slack_team_name = models.CharField(max_length=255, blank=True)
    slack_team_id = models.CharField(max_length=255, blank=True)
    slack_feedback_channel_name = models.CharField(choices=[], max_length=255, blank=True)
    slack_feedback_channel_id = models.CharField(max_length=255, blank=True)

    # From User
    slack_user_access_token = models.CharField(max_length=255, blank=True)
    slack_user_id = models.CharField(max_length=255, blank=True)

    objects = SlackSettingsManager()
