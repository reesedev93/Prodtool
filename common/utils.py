import re
from importlib import import_module

from bs4 import BeautifulSoup
from django.template.defaultfilters import truncatechars
from markdown import markdown


def get_class(fully_qualified_class_name):
    """
    Given a fully qualified class name e.g. my.module.ClassName returns the class.
    """
    parts = fully_qualified_class_name.split(".")
    module_name = ".".join(parts[:-1])
    module = import_module(module_name)
    klass_name = parts[-1]
    return getattr(module, klass_name)


def textify_html(html, join_char="\n"):
    soup = BeautifulSoup(html, features="html.parser")

    # kill all script and style elements
    for script in soup(["script", "style"]):
        script.extract()  # rip it out

    # get text
    return soup.get_text(join_char)


def remove_markdown(markdown_text, length=None, join_char="\n"):
    html = markdown(markdown_text)
    clean_text = textify_html(html, join_char)
    if length:
        clean_text = truncatechars(clean_text, length)
    return clean_text


def email_list_from_string(email_string):
    split_emails = re.split(r"[\s\n,;]", email_string)
    emails_list = []
    for email in split_emails:
        email = email.strip()
        if email:
            emails_list.append(email)
    return emails_list
