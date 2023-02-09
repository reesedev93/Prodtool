from django.contrib import admin
from .models import SlackSettings

class SlackSettingsAdmin(admin.ModelAdmin):
    list_display = ('customer_id', 'customer', 'user', 'slack_bot_user_id', 'slack_team_name', 
                    'slack_team_id', 'slack_feedback_channel_name', 
                    'slack_feedback_channel_id', 'slack_user_id')
    
admin.site.register(SlackSettings, SlackSettingsAdmin)
