import requests
from django import forms


class SlackChooseChannelForm(forms.Form):
    slack_feedback_channel_id = forms.ChoiceField(
        choices=[],
        label="Which channel is your customer feedback posted to?",
        required=False,
    )

    # This init method is run before forms.ModelForm's init method (which is called below)
    def __init__(self, *args, **kwargs):
        # Get user out of kwargs before calling forms.modelForm's init method
        self.user = kwargs.pop("user")

        # Call Parent's init method (e.g. forms.ModelForm) without user as a kwarg
        super(SlackChooseChannelForm, self).__init__(*args, **kwargs)

        self.slack_channels = self.get_slack_channels(self.user)
        self.fields["slack_feedback_channel_id"].choices = [
            ("", "")
        ] + self.slack_channels
        self.fields[
            "slack_feedback_channel_id"
        ].initial = self.user.customer.slack_settings.slack_feedback_channel_id

    def save(self, commit=True):
        self.user.customer.slack_settings.slack_feedback_channel_id = self.cleaned_data[
            "slack_feedback_channel_id"
        ]

        channel_dict = dict(self.slack_channels)

        if self.cleaned_data["slack_feedback_channel_id"]:
            channel_name = channel_dict[self.cleaned_data["slack_feedback_channel_id"]]
            self.user.customer.slack_settings.slack_feedback_channel_name = channel_name
        else:
            self.user.customer.slack_settings.slack_feedback_channel_name = ""

        self.user.customer.slack_settings.save()

    def get_slack_channels(self, user):
        channels_list = []
        channels_url = "https://slack.com/api/conversations.list"
        data = {
            "token": user.customer.slack_settings.slack_bot_token,
            "exclude_archived": "true",
            "limit": "1000",
            "types": "public_channel",
        }

        response = requests.post(channels_url, data)

        # In case of error you get json like:
        # {'ok': False, 'error': 'not_authed'}
        if response.ok and response.json().get("ok", False):
            for i in response.json().get("channels"):
                if i["is_channel"] and not i["is_archived"]:
                    k = (i["id"], i["name"])
                    channels_list.append(k)

        channels_list = sorted(channels_list, key=lambda item: item[1].lower())
        return channels_list
