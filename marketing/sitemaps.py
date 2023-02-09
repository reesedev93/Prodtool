import datetime
import json

import requests
from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from marketing import urls


class StaticSitemap(Sitemap):
    priority = 0.5
    changefreq = "weekly"

    # The below method returns all urls defined in urls.py file
    def items(self):
        mylist = []
        # Hide the below from appearing in the sitemap.
        hide_from_sitemap = [
            "django.contrib.sitemaps.views.sitemap",
            "marketing-intercom-test-data",
            "marketing-headless-cms-fallback",
            "marketing-appsumo",
        ]
        for url in urls.urlpatterns:
            if url.name not in hide_from_sitemap:
                mylist.append(url.name)

        # Build list from StoryBlok
        url = f"https://api.storyblok.com/v1/cdn/links?cv={datetime.datetime.now().timestamp()}&token={settings.STORYBLOK_API_TOKEN}&version=published"
        response = requests.request("GET", url)

        for item in json.loads(response.text)["links"].items():
            obj = item[1]
            if obj["published"] is True and obj["is_folder"] is False:
                mylist.append(f'/{item[1]["slug"]}/')

        return mylist

    def location(self, item):
        # item is either a StoryBlok path to an article like "/article-path" or
        # a named route like "marketing-home".
        #
        # If an item has a slash in it it's from Storyblok and is already a
        # named route. In this case we can just return the item.
        #
        # If an item is a named route we need to call reverse(item) to get the
        # article path.

        if "/" in item:
            return item
        else:
            return reverse(item)
