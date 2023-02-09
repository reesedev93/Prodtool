import logging
from urllib.parse import urljoin

import requests

API_BASE = "https://api.helpscout.net/v2/"


class ApiException(Exception):
    def __init__(self, status_code, message):
        self.status_code = status_code
        Exception.__init__(self, message)


class Client(object):
    logger = logging.getLogger(__name__)
    API_BASE = "https://api.helpscout.net/v2/"

    def __init__(
        self,
        access_token,
        refresh_token,
        client_id,
        client_secret,
        save_refreshed_tokens,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.save_refreshed_tokens = save_refreshed_tokens
        self.client_id = client_id
        self.client_secret = client_secret

    def get_headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
        }

    def call_server(self, api, method, data=None):
        response = self._call_server(api, method, data=data)
        if response.status_code == 401:
            response = self.refresh_auth_token()
            response = self._call_server(api, method, data=data)
        self.check_response(response)
        return response

    def _call_server(self, api, method, data=None):
        url = urljoin(API_BASE, api)
        self.logger.info(f"Help Scout API: {method} {url} with {data}")

        if method == "get":
            response = requests.get(url, headers=self.get_headers())
        elif method == "delete":
            response = requests.delete(url, headers=self.get_headers())
        elif method == "post":
            response = requests.post(url, json=data, headers=self.get_headers())
        elif method == "patch":
            response = requests.patch(url, json=data, headers=self.get_headers())
        else:
            raise Exception("Invalid http method")
        return response

    def check_response(self, response):
        if not response.ok:
            self.logger.info(
                f"Status code: {response.status_code}. Message: {response.text}"
            )
            raise ApiException(response.status_code, response.text)

    def get_auth_token(self, code):
        data = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
        }
        response = self._call_server("oauth2/token", "post", data=data)

        d = response.json()
        self.access_token = d["access_token"]
        self.refresh_token = d["refresh_token"]

        return response

    def refresh_auth_token(self):
        data = {
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }
        response = self._call_server("oauth2/token", "post", data=data)
        d = response.json()
        try:
            self.access_token = d["access_token"]
            self.refresh_token = d["refresh_token"]

            # Call the function pointer that was passed in that's responsilbe
            # for saving our refreshed tokens.
            self.save_refreshed_tokens(self.access_token, self.refresh_token)
        except KeyError:
            self.logger.warn(
                f"Help Scout: Wasn't able to refresh access token: '{self.access_token}'"
            )
        return response

    def get_resource_owner(self):
        return self.call_server("users/me", "get")

    def get_webhooks(self):
        return self.call_server("webhooks", "get")

    def delete_webhook(self, url):
        return self.call_server(url, "delete")

    def delete_our_webhooks(self):
        try:
            response = self.get_webhooks()
            for item in response.json()["_embedded"]["webhooks"]:
                target = item["url"]
                link = item["_links"]["self"]["href"]
                if "/app/integrations/helpscout/receive-webhook/" in target:
                    self.delete_webhook(link)
        except KeyError:
            # Better error handling here wouldn't hurt but quite possibly
            # we can't get our webhooks when we need to delete them because
            # we don't have access now.
            pass
        except ApiException as e:
            self.logger.error(f"Failed to delete Help Scout web hooks. Error: {e}")

    def create_webhook(self, webhook_url, events, secret, label):
        data = {
            "url": webhook_url,
            "events": events,
            "secret": secret,
            "label": label,
        }
        return self.call_server("webhooks", "post", data=data)

    def get_conversation(self, id):
        return self.call_server(f"conversations/{id}", "get")

    def update_conversation(self, id, path, op, value):
        valid_values = {
            "/subject": ["replace",],
            "/primaryCustomer.id": ["replace",],
            "/draft": ["replace",],
            "/mailboxId": ["move",],
            "/status": ["replace",],
            "/assignTo": ["replace", "remove",],
        }

        try:
            if op not in valid_values[path]:
                raise ApiException(f"Invalid op '{op}' for path '{path}'.")
        except KeyError:
            raise ApiException(f"Invalid path '{path}'.")

        data = {
            "op": op,
            "path": path,
            "value": value,
        }
        return self.call_server(f"conversations/{id}", "patch", data=data)

    def get_tags(self):
        response = self.call_server("tags/", "get")
        paging_info = response.json()["page"]
        tags = response.json()["_embedded"]["tags"]
        for page_num in range(2, paging_info["totalPages"] + 1):
            response = self.call_server(f"tags/?page={page_num}", "get")
            tags.extend(response.json()["_embedded"]["tags"])
        return tags

    def get_customer(self, id):
        return self.call_server(f"customers/{id}", "get")

    def create_note(self, note_text, conversation_id, hs_user_id):
        data = {
            "text": note_text,
        }

        if hs_user_id:
            data["user"] = hs_user_id

        response = self.call_server(
            f"conversations/{conversation_id}/notes", "post", data
        )
        return response
