import re

import requests
from celery import shared_task
from django.core.mail import mail_admins
from django.template import loader
from django.utils import timezone

from .models import Source


@shared_task
def monitor_hn():
    """
    Sends us an email if there has been a new item on hn that matches keywords
    we care about.
    """

    regexs_to_match = (
        r"canny",
        r"uservoice",
        r"productboard",
        r"savio",
        r"\bPM\b",
        r"product manag",
        r"roadmap",
        r"user feedback",
        r"customer feedback",
        r"product feedback",
        r"feature request",
    )

    start_time = timezone.now()

    max_item = requests.get(
        "https://hacker-news.firebaseio.com/v0/maxitem.json?print=pretty"
    ).json()
    source, created = Source.objects.get_or_create(
        name="HN", defaults={"last_checked": max_item - 100}
    )
    if created:
        print("monitor_hn: created LastChecked row")

    total_to_check = max_item - source.last_checked
    print(f"monitor_hn: being processing {total_to_check} items on HN for mentions")

    formated_matches = "\n* ".join(regexs_to_match)
    print(f"monitor_hn: items checked for matches to:\n{formated_matches}")

    mentions = []
    for id in range(source.last_checked + 1, max_item + 1):
        response = requests.get(
            f"https://hacker-news.firebaseio.com/v0/item/{id}.json?print=pretty"
        )
        item = response.json()
        if not item:
            print(
                f"monitor_hn: no item returned for id {id}. Response: {response.status_code} - {response.content}"
            )
            continue
        title = item.get("title", "")
        text = item.get("text", "")

        to_check = f"{title} {text}"
        for regex in regexs_to_match:
            # print(f"Checking: {regex} against {to_check}")
            if re.search(regex, to_check, re.I | re.M):
                print(item)
                mentions.append((regex, item))
                break

    total_time_to_process = timezone.now() - start_time
    print(f"monitor_hn: total time to process: {total_time_to_process}")
    context = {
        "total_time_to_process": total_time_to_process,
        "mentions": mentions,
        "regexs_to_match": regexs_to_match,
        "total_to_check": total_to_check,
    }

    if mentions:
        subject = "[Savio]: There's an HN mention check it out and respond!"

        txt_message = "This is an HTML email sucker!"
        html_message = loader.render_to_string("email/hn_mentions.html", context)

        mail_admins(subject, txt_message, html_message=html_message)

    source.last_checked = max_item
    source.save()
    print(f"monitor_hn: updated last_checked to: {source.last_checked}")
