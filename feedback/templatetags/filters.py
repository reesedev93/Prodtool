from bs4 import BeautifulSoup
from django import template
from django.contrib.messages import constants as DEFAULT_MESSAGE_LEVELS
from django.http.request import QueryDict
from django.template import Context
from django.template.defaultfilters import pluralize
from django.template.loader import get_template
from django.utils import timezone
from django.utils.safestring import mark_safe
from markdown import markdown
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from common import utils

register = template.Library()


class InlineImageProcessor(Treeprocessor):
    def run(self, root):
        for element in root.iter("img"):
            element.set("class", "img-border img-fluid")


class EscapeHtml(Extension):
    def extendMarkdown(self, md, md_globals):
        del md.preprocessors["html_block"]
        del md.inlinePatterns["html"]


class ImageStyling(Extension):
    def extendMarkdown(self, md):
        # Register the new treeprocessor
        md.treeprocessors.register(InlineImageProcessor(md), "inlineimageprocessor", 15)


@register.filter
def markdownify(text):
    # the user might have put <html> tags in. We need to escape those
    # then we are going to turn the markdown to html and we want to
    # dump that *unescaped* onto the page.
    # We can't ust use django.utils.html.escape because that will escape
    # just plan old '>' chars which are used in markdown for indicating
    # quotes and if those get escaped then email that get forwarded in
    # will look like ass.
    # See:
    # https://python-markdown.github.io/change_log/release-2.6/#safe_mode-deprecated
    # for where EscapeHtml() comes from.

    # RE: nl2br see: https://python-markdown.github.io/extensions/nl2br/
    # When using the editor users can add linebreaks and the WYSIWYG
    # is borked if we don't respect them. This is what Stack and GitHub
    # do we're in good company.
    text_as_html = markdown(text, extensions=[EscapeHtml(), "nl2br", "prependnewline"])
    return mark_safe(f'<div class="markdownified">{text_as_html}</div>')


@register.simple_tag(takes_context=False)
def headless_markdownify(text, prependnewline=True, parent_element_classes=[]):
    # This method is used to turn markdown received from our headless CMS into
    # HTML.  Not we assume anything in our CMS is safe - we don't escape HTML
    # in this method.
    # Note we also add img-fluid and img-border classes to ALL images
    # sent over from the CMS using the ImageStyling() extension.

    # RE: nl2br see: https://python-markdown.github.io/extensions/nl2br/
    # When using the editor users can add linebreaks and the WYSIWYG
    # is borked if we don't respect them. This is what Stack and GitHub
    # do we're in good company.

    # parent_element_classes is a list of classes to apply to the parent element
    # that's returned from the markdown() method.

    # To call this in your template use e.g.
    # {% headless_markdownify item.list False 'list-unstyled feature-list' %}

    if prependnewline:
        extensions = [ImageStyling(), "nl2br", "prependnewline"]
    else:
        extensions = [ImageStyling(), "nl2br"]

    text_as_html = markdown(text, extensions=extensions)

    if parent_element_classes:
        soup = BeautifulSoup(text_as_html)

        # Don't assume there's a first element.  Wrap this in a try/catch for an index error.
        try:
            soup.find_all()[0]["class"] = parent_element_classes
            text_as_html = soup
        except IndexError:
            pass

    return mark_safe(f"{text_as_html}")


@register.filter
def remove_markdown(text):
    return utils.remove_markdown(text)


@register.filter
def has_feedback(feature_request):
    return feature_request.feedback_set.count() > 0


@register.simple_tag(takes_context=False)
def is_triaged(feedback_state):
    if feedback_state == "ACTIVE":
        return False
    else:
        return True


@register.filter
def friendly_feedback_state(state):
    if state == "ACTIVE":
        return mark_safe(
            "<i class='fas fa-inbox' data-original-title='This feedback is untriaged, so it also appears in your Feedback Inbox until you mark it as Triaged.' data-toggle='tooltip'></i>"
        )
    else:
        return mark_safe(
            "<i class='fas fa-archive' data-original-title='You have triaged this feedback' data-toggle='tooltip'></i>"
        )


@register.filter
def badge(feedback_type):
    if feedback_type == "ACTIVE":
        return "teal"
    elif feedback_type == "CHURNED":
        return "danger"
    elif feedback_type == "LOST DEAL":
        return "pink"
    else:
        return "light"


@register.simple_tag(takes_context=True)
def active_class(context, qs_to_match):
    # Give back the acitve class if the passed in qs
    # matches the current qs. We are being a bit stupid
    # here. Should limit the keys we are checking to only
    # keys that are part of the fitler but it's not an issue
    # currently.
    if set(QueryDict(qs_to_match).items()) == set(context["request"].GET.items()):
        active_class = "active"
    else:
        active_class = ""
    return active_class


@register.filter
def notification_class_type(message_level):
    if message_level == DEFAULT_MESSAGE_LEVELS.ERROR:
        return "danger"
    elif message_level == DEFAULT_MESSAGE_LEVELS.WARNING:
        return "warning"
    elif message_level == DEFAULT_MESSAGE_LEVELS.SUCCESS:
        return "success"
    else:
        return "primary"


@register.simple_tag(takes_context=True)
def cookie_value(context, cookie_name):
    req = context["request"]
    return req.COOKIES.get(cookie_name, "true")


@register.simple_tag(takes_context=True)
def is_old_onboarding(context):
    if context["request"].GET.get("onboarding_inbox", "None") == "1":
        return True
    else:
        return False


@register.simple_tag(takes_context=True)
def show_filters(context):
    if context["request"].GET.get("filter", "None") == "1":
        return True
    else:
        return False


@register.simple_tag(takes_context=False)
def landing_page_class(index):
    if index % 2 == 0:
        return "bg-faded"
    else:
        return "bg-white"


@register.simple_tag(takes_context=True)
def get_plan_from_qs(context):
    return context["request"].GET.get("plan", "None")


@register.simple_tag(takes_context=True)
def from_onboarding(context):
    if context["request"].GET.get("from", "None") == "onboarding":
        return True
    else:
        return False


@register.simple_tag(takes_context=True)
def onboarding_param(context):
    if context["request"].GET.get("onboarding", "") == "1":
        return "onboarding=1"
    else:
        return ""


@register.simple_tag(takes_context=True)
def onboarding_current_class(context, current_step):
    if current_step in context["request"].get_full_path():
        return "active current"
    else:
        return " "


@register.simple_tag(takes_context=False)
def onboarding_step_done(this_step, done_step):
    if this_step == "tour":
        if (
            done_step == "tour"
            or done_step == "customer-data"
            or done_step == "chrome-extension"
            or done_step == "whitelist"
        ):
            return "done"
        else:
            return ""
    elif this_step == "customer-data":
        if (
            done_step == "customer-data"
            or done_step == "chrome-extension"
            or done_step == "whitelist"
            or done_step == "done"
        ):
            return "done"
        else:
            return ""
    elif this_step == "chrome-extension":
        if (
            done_step == "chrome-extension"
            or done_step == "whitelist"
            or done_step == "done"
        ):
            return "done"
        else:
            return ""
    elif this_step == "whitelist":
        if done_step == "whitelist" or done_step == "done":
            return "done"
        else:
            return ""
    elif this_step == "done":
        if done_step == "done":
            return "done"
        else:
            return ""


@register.simple_tag(takes_context=True)
def get_feedback_page(context):
    path = context["request"].path
    if "feature-request" in path:
        return "fr_details"
    elif "inbox" in path:
        return "inbox"
    elif "app/feedback" in path:
        return "feedback_details"


@register.simple_tag(takes_context=True)
def get_done_step(context):
    path = context["request"].path
    if "tour" in path:
        return " "
    elif "customer-data" in path:
        return "tour"
    elif "chrome-extension" in path:
        return "customer-data"
    elif "whitelist" in path:
        return "chrome-extension"
    elif "done" in path:
        return "whitelist"


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.simple_tag(takes_context=True)
def hide_sidebar(context, dom_element):
    request = context["request"]
    cookie = request.COOKIES.get("showSidebar", "true")

    # KM: Uncomment this block and delete everything after this line in the hide_sidebar method
    #     to disable flyout
    #    if cookie == "false":
    #      if dom_element == "sidebar":
    #        return "aside-folded"
    #      elif dom_element == "sidebar_link":
    #        return "display: none;"
    #      elif dom_element == "toggler":
    #        return "toggler-folded"
    #      else:
    #        return ""
    #    else:
    #      return ""

    if cookie == "false":
        if dom_element == "sidebar":
            return "aside-folded"
        elif dom_element == "sidebar_link":
            return ""
        elif dom_element == "toggler":
            return "toggler-folded"
        else:
            return ""
    else:
        return ""


@register.filter
def as_bootstrap_label(field, label_class=""):
    attributes = {
        "field": field,
        "label_class": label_class,
    }

    template = get_template("filters/bootstrap_label.html")

    c = Context(attributes).flatten()
    return template.render(c)


@register.filter
def as_bootstrap_help_text(field):
    attributes = {
        "field": field,
    }

    template = get_template("filters/bootstrap_help_text.html")

    c = Context(attributes).flatten()
    return template.render(c)


@register.simple_tag
def get_mrr(user, fa):
    if user:
        mrr = user.get_mrr_fast(fa)
    else:
        mrr = None
    return mrr


@register.simple_tag
def get_plan(user, fa):
    if user:
        plan = user.get_plan_fast(fa)
    else:
        plan = None
    return plan


@register.simple_tag
def get_attribute_display_string(user_or_company, display_attributes):
    if user_or_company:
        items = []
        for fa in display_attributes:
            attribute = user_or_company.filterable_attributes.get(fa.name, "Unknown")
            items.append(f"{fa.friendly_name}: {attribute}")
        display_string = " • ".join(items)
    else:
        display_string = ""
    return display_string


@register.simple_tag
def get_display_attributes(user_or_company, display_attributes):
    # A list of tuple pairs [(frienldy_name, value),...]
    if user_or_company:
        items = []
        for fa in display_attributes:
            attribute = user_or_company.filterable_attributes.get(fa.name, "Unknown")
            items.append((fa.friendly_name, attribute))
    else:
        items = []
    return items


@register.filter
def friendly_time_ago(t1):
    # ALERT! You probably don't want to use this. Use Djagno built in timesince instead
    t = timezone.now() - t1
    elaspsed_seconds = t.total_seconds()
    elaspsed_hours = int(elaspsed_seconds // 60 // 60)
    # If the difference between now and the passed-in date is greater than 24 hours,
    # we return the difference in days.  If it's less than 24 hours, we return the
    # difference in hours.
    if elaspsed_hours >= 24:
        days = int(elaspsed_hours // 24)
        friendly_string = f"{days} day{pluralize(days)}"
    else:
        friendly_string = f"{elaspsed_hours} hour{pluralize(elaspsed_hours)}"
    return friendly_string


@register.simple_tag
def get_problem_snippet_with_no_linebreaks(feedback, num_chars=1000):
    return feedback.get_problem_snippet(num_chars, "")
