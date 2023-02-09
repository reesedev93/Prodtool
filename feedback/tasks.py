import csv
import pickle
from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMessage
from django.template import loader
from django.utils import timezone
from io import StringIO
from accounts.models import Customer, User, StatusEmailSettings
from appaccounts.models import FilterableAttribute
from .models import CustomerFeedbackImporterSettings, FeatureRequest, Feedback
from .admin_csv_importer import AdminCsvFeedbackImport

@shared_task
def import_feedback(cfis_id, notify_user_id):
    try:
        cfis = CustomerFeedbackImporterSettings.objects.get(pk=cfis_id)
        cfis.do_import()
        if notify_user_id:
            notify_user = User.objects.get(customer=cfis.customer, pk=notify_user_id)
            subject = "Your Customer Data import is done."
            txt_message = loader.render_to_string('email/intercom_import_finished.txt', {})

            notify_user.email_user(subject, txt_message)

    except CustomerFeedbackImporterSettings.DoesNotExist:
        print(f"Didn't execute import_feedback because #{cfis_id} doesn't exist")

@shared_task
def unsnooze_feedback():
    Feedback.objects.unsnooze_feedback()

@shared_task
def admin_csv_feedback_import(customer_id, filename, import_type):
    try:
        customer = Customer.objects.get(id=customer_id)
        importer = AdminCsvFeedbackImport(customer, filename, import_type)
        importer.do_import()
    except Customer.DoesNotExist:
        print(f"Customer with id #{customer_id} doesn't exist")

@shared_task
def send_status_emails(min_interval=20):
    """
    Send status emails.
    `min_interval` is the smallest number of hours that can have
    passed between invocations before sending will be skipped.
    This is a failsafe to ensure we don't inadvertanly send a
    flood of emails.
    """
    for ses in StatusEmailSettings.objects.filter(notify=StatusEmailSettings.NOTIFY_DAILY):
        seconds_since_last_email = (timezone.now() - ses.last_notified).total_seconds()
        min_interval_seconds = min_interval * 60 * 60
        if seconds_since_last_email < min_interval_seconds:
            print(f"Skipping status email for {ses.user.email} due to min_interval")
            continue

        new_feedback = Feedback.objects.filter(
            customer=ses.customer,
            created__gte=ses.last_notified)
        new_feature_requests = FeatureRequest.objects.filter(
            customer=ses.customer,
            created__gte=ses.last_notified).with_counts(ses.customer)

        total_untriaged_feedback = Feedback.objects.filter(
            customer=ses.customer,
            state=Feedback.ACTIVE).count()


        context = {
            'ses': ses,
            'host': settings.HOST,
            'new_feedback': new_feedback,
            'total_new_feedback': new_feedback.count(),
            'total_untriaged_feedback': total_untriaged_feedback,
            'new_feature_requests': new_feature_requests,
            'total_new_feature_requests': new_feature_requests.count(),
            'mrr_attribute': FilterableAttribute.objects.get_mrr_attribute(ses.customer),
            'plan_attribute': FilterableAttribute.objects.get_plan_attribute(ses.customer),
            'company_display_attributes': FilterableAttribute.objects.get_company_display_attributes(ses.customer),
            'user_display_attributes': FilterableAttribute.objects.get_user_display_attributes(ses.customer),
            'last_notified':  ses.last_notified,
            'customer': ses.customer,
            'user': ses.user,
        }

        if new_feature_requests.count() > 0 or new_feedback.count() > 0:
          fr_text = "feature requests"
          if new_feature_requests.count() == 1:
            fr_text = "feature request"

          subject = f"[Digest]: {new_feedback.count()} new feedback & {new_feature_requests.count()} new {fr_text}"

          txt_message = loader.render_to_string('email/status_email.txt', context)
          # html_message = loader.render_to_string('email/status_email_generated_inline.html', context)
          html_message = loader.render_to_string('email/status_email.html', context)
          ses.user.email_user(subject, txt_message, html_message=html_message)
          ses.first_email_sent = True
          ses.last_notified = timezone.now()
          ses.save()

@shared_task(serializer='pickle')
def export_feature_requests_to_csv(notify_user_id, pickled_fr_qs, pickled_feedback_qs):
    csvfile = StringIO()
    writer = csv.writer(csvfile)

    user = User.objects.get(id=notify_user_id)
    user_fas = FilterableAttribute.objects.get_user_display_attributes(user.customer)
    company_fas = FilterableAttribute.objects.get_company_display_attributes(user.customer)
    headers = [
        'Feature Request',
        'Description',
        'Status',
        'Priority',
        'Effort',
        'Feature Request Themes',
        'Feedback',
        'Feedback From',
        'Feedback Themes',
        'Feedback Created',
        'Person Name',
        'Person Email',
        'Company',
        FilterableAttribute.objects.get_plan_display_name(user.customer),
        FilterableAttribute.objects.get_mrr_display_name(user.customer),
    ]
    headers.extend([f"{fa.friendly_name} (Person)" for fa in user_fas])
    headers.extend([f"{fa.friendly_name} (Company)" for fa in company_fas])
    writer.writerow(headers)

    feature_requests = FeatureRequest.objects.all()
    feature_requests.query = pickle.loads(pickled_fr_qs)
    feature_requests.filter(customer=user.customer) # extra safety

    feedback_qs = Feedback.objects.all()
    feedback_qs.query = pickle.loads(pickled_feedback_qs)
    feedback_qs.filter(customer=user.customer) # extra safety

    for fr in feature_requests:
        feedback_for_fr = feedback_qs.filter(
            customer=user.customer,
            feature_request=fr)

        if feedback_for_fr.exists():
            for feedback in feedback_for_fr:
                if feedback.user:
                    name = feedback.user.name
                    email = feedback.user.email
                    plan = feedback.user.get_plan()
                    mrr = feedback.user.get_mrr()
                    if feedback.user.company:
                        company = feedback.user.company.name
                    else:
                        company = ''
                else:
                    name = ''
                    email = ''
                    company = ''

                row = [
                    fr.title,
                    fr.description,
                    fr.get_state_display(),
                    fr.get_priority_display(),
                    fr.get_effort_display(),
                    ",".join((theme.title for theme in fr.themes.all())),
                    feedback.problem,
                    feedback.get_feedback_type_display(),
                    ",".join((theme.title for theme in feedback.themes.all())),
                    feedback.created,
                    name,
                    email,
                    company,
                    plan,
                    mrr,
                ]

                for fa in user_fas:
                    if feedback.user:
                        row.append(feedback.user.filterable_attributes.get(fa.name, ''))
                    else:
                        row.append("")

                for fa in company_fas:
                    if feedback.user and feedback.user.company:
                        row.append(feedback.user.company.filterable_attributes.get(fa.name, ''))
                    else:
                        row.append("")
                writer.writerow(row)
        else:
            row = [
                fr.title,
                fr.description,
                fr.get_state_display(),
                fr.get_priority_display(),
                fr.get_effort_display(),
                ",".join((theme.title for theme in fr.themes.all())),
            ]
            writer.writerow(row)


    subject = "[Savio] Your feature request export is complete"
    msg = f"Hi {user.first_name},\n\nYour feature request CSV export is attached.\n\nCan we make this better? Have questions? Hit reply and we'll answer.\n\n- The Savio Team"
    to = [user.email,]

    filename = "savio_feature_request_export_%s.csv" % (timezone.now())
    message = EmailMessage(subject, msg, to=to)
    message.attach(filename, csvfile.getvalue(), 'text/csv')
    message.send()

@shared_task(serializer='pickle')
def export_feedback_to_csv(notify_user_id, pickled_feedback_qs):
    csvfile = StringIO()
    writer = csv.writer(csvfile)

    user = User.objects.get(id=notify_user_id)
    user_fas = FilterableAttribute.objects.get_user_display_attributes(user.customer)
    company_fas = FilterableAttribute.objects.get_company_display_attributes(user.customer)
    headers = [
        'Feedback',
        'Feedback From',
        'Feedback Themes',
        'Feedback Created',
        'Source',
        'Feature Request',
        'Description',
        'Status',
        'Priority',
        'Effort',
        'Feature Request Themes',
        'Person Name',
        'Person Email',
        'Company',
        FilterableAttribute.objects.get_plan_display_name(user.customer),
        FilterableAttribute.objects.get_mrr_display_name(user.customer),
    ]
    headers.extend([f"{fa.friendly_name} (Person)" for fa in user_fas])
    headers.extend([f"{fa.friendly_name} (Company)" for fa in company_fas])
    writer.writerow(headers)
    feedback_qs = Feedback.objects.all()
    feedback_qs.query = pickle.loads(pickled_feedback_qs)
    feedback_qs.filter(customer=user.customer) # extra safety

    for feedback in feedback_qs:
        if feedback.user:
            name = feedback.user.name
            email = feedback.user.email
            plan = feedback.user.get_plan()
            mrr = feedback.user.get_mrr()
            if feedback.user.company:
                company = feedback.user.company.name
            else:
                company = ''
        else:
            name = ''
            email = ''
            company = ''
            plan = ''
            mrr = ''

        if feedback.feature_request:
            fr_title = feedback.feature_request.title
            fr_description = feedback.feature_request.description
            fr_state = feedback.feature_request.get_state_display()
            fr_priority = feedback.feature_request.get_priority_display()
            fr_effort = feedback.feature_request.get_effort_display()
            fr_themes = ",".join((theme.title for theme in feedback.feature_request.themes.all()))
        else:
            fr_title = ""
            fr_description = ""
            fr_state = ""
            fr_priority = ""
            fr_effort = ""
            fr_themes = ""

        row = [
            feedback.problem,
            feedback.get_feedback_type_display(),
            ",".join((theme.title for theme in feedback.themes.all())),
            feedback.created,
            feedback.source_url,
            fr_title,
            fr_description,
            fr_state,
            fr_priority,
            fr_effort,
            fr_themes,
            name,
            email,
            company,
            plan,
            mrr,
        ]

        for fa in user_fas:
            if feedback.user:
                row.append(feedback.user.filterable_attributes.get(fa.name, ''))
            else:
                row.append("")

        for fa in company_fas:
            if feedback.user and feedback.user.company:
                row.append(feedback.user.company.filterable_attributes.get(fa.name, ''))
            else:
                row.append("")
        writer.writerow(row)


    subject = "[Savio] Your feedback export is complete"
    msg = f"Hi {user.first_name},\n\nYour feedback CSV export is attached.\n\nCan we make this better? Have questions? Hit reply and we'll answer.\n\n- The Savio Team"
    to = [user.email,]

    filename = "savio_feedback_export_%s.csv" % (timezone.now())
    message = EmailMessage(subject, msg, to=to)
    message.attach(filename, csvfile.getvalue(), 'text/csv')
    message.send()
