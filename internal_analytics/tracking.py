import analytics as segment

EVENT_SOURCE_CE = 'CHROME_EXTENSION'
EVENT_SOURCE_WEB_APP = 'WEB_APP'
EVENT_SOURCE_SLACK = 'SLACK'
EVENT_SOURCE_API = 'API'

def account_created(user):
    segment.track(user.id, 'Account Created', {
        'customer': user.customer.id,
        'customer_name': user.customer.name,
        'email': user.email,
        'name': f"{user.first_name} {user.last_name}",
        'role': user.job,
    })

def user_created(user, event_source):
    segment.track(user.id, 'User Created', {
        'customer': user.customer.id,
        'customer_name': user.customer.name,
        'event_source': event_source,
        'email': user.email,
        'name': f"{user.first_name} {user.last_name}",
        'role': user.job,
    })

def feedback_created(user_id, customer, feedback, event_source):
    segment.track(user_id, 'Feedback Created', {
        'customer': customer.id,
        'customer_name': customer.name,
        'event_source': event_source,
        'feature_attached': feedback.feature_request is not None,
        'feedback_type': feedback.feedback_type,
        'user_attached': feedback.user is not None,
        'solution_provided': feedback.solution != "",
        'souce_username': feedback.source_username,
    })
  


def feedback_edited(user):
    segment.track(user.id, 'Feedback Edited', {
        'user_email': user.email,
        'user_name': f"{user.first_name} {user.last_name}",
        'customer': user.customer.id,
        'customer_name': user.customer.name,
    })

def feedback_triaged(user, feedback, days):
    if days:
        segment.track(user.id, 'Feedback Snoozed', {
            'user_email': user.email,
            'user_name': f"{user.first_name} {user.last_name}",
            'customer': user.customer.id,
            'customer_name': user.customer.name,
            'days': days,
        })
    else:
        segment.track(user.id, 'Feedback Triaged', {
            'user_email': user.email,
            'user_name': f"{user.first_name} {user.last_name}",
            'customer': user.customer.id,
            'customer_name': user.customer.name,
        })

def feedback_list_viewed(user, list_filter):
    segment.track(user.id, 'Feedback Viewed', {
        'user_email': user.email,
        'user_name': f"{user.first_name} {user.last_name}",
        'customer': user.customer.id,
        'customer_name': user.customer.name,
        'filter': list_filter,
    })

def feature_request_created(user, event_source):
    segment.track(user.id, 'Feature Request Created', {
        'user_email': user.email,
        'user_name': f"{user.first_name} {user.last_name}",
        'customer': user.customer.id,
        'customer_name': user.customer.name,
        'event_source': event_source,
    })


def customer_email_sent(sender, recipient, email_type):
    recipient_company_id = -1
    recipient_company_name = ""
    if recipient.company:
        recipient_company_id = recipient.company.id
        recipient_company_name = recipient.company.name

    segment.track(sender.id, 'Customer Email Sent', {
        'user_id': recipient.id,
        'user_email': recipient.email,
        'user_name': recipient.name,
        'company_id': recipient_company_id,
        'company_name': recipient_company_name,
        'email_type': email_type
    })

def feature_request_edited(user):
    segment.track(user.id, 'Feature Request Edited', {
        'user_email': user.email,
        'user_name': f"{user.first_name} {user.last_name}",
        'customer': user.customer.id,
        'customer_name': user.customer.name,
    })

def feature_request_list_viewed(user, list_filter):
    segment.track(user.id, 'Feature Request Viewed', {
        'user_email': user.email,
        'user_name': f"{user.first_name} {user.last_name}",
        'customer': user.customer.id,
        'customer_name': user.customer.name,
        'filter': list_filter,
    })

def feature_request_feedback_details_viewed(user):
    segment.track(user.id, 'Feature Request Feedback Details Viewed', {
        'user_email': user.email,
        'user_name': f"{user.first_name} {user.last_name}",
        'customer': user.customer.id,
        'customer_name': user.customer.name,
    })

def theme_created(user):
    segment.track(user.id, 'Theme Created', {
        'user_email': user.email,
        'user_name': f"{user.first_name} {user.last_name}",
        'customer': user.customer.id,
        'customer_name': user.customer.name,
    })


def integration_connected(user, event_source):
    segment.track(user.id, 'Integration Connected', {
        'customer': user.customer.id,
        'customer_name': user.customer.name,
        'event_source': event_source,
        'email': user.email,
        'name': f"{user.first_name} {user.last_name}",
        'role': user.job,
    })


def integration_disconnected(user, event_source):
    segment.track(user.id, 'Integration Disconnected', {
        'customer': user.customer.id,
        'customer_name': user.customer.name,
        'event_source': event_source,
        'email': user.email,
        'name': f"{user.first_name} {user.last_name}",
        'role': user.job,
    })
