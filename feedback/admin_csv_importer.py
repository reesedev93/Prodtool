import csv
import uuid
import datetime
from django.core.mail import mail_admins
from html2text import html2text
from appaccounts.models import AppUser, AppCompany
from common.utils import textify_html
from feedback.models import FeatureRequest, Feedback, Theme
from .admin_forms import UploadFeedbackForm

class AdminCsvFeedbackImport(object):
    def __init__(self, customer, filename, import_type):
        self.invalid_rows = list()
        self.total_fr_imported = 0
        self.total_feedback_imported = 0
        self.total_companies_imported = 0
        self.total_users_imported = 0
        self.total_themes_imported = 0
        self.import_token = ""
        self.customer = customer
        self.filename = filename
        self.import_type = import_type

    def do_import(self):
        self.import_token = str(uuid.uuid4())

        with open(self.filename, 'r', encoding="utf-8") as f:
            csv_file = csv.DictReader(f)
            self.problems = self.validate_required_columms(csv_file.fieldnames)
            if not self.problems:
                for row in csv_file:
                    print(row)
                    if self.validate_row(row, self.import_type):
                        if self.import_type in (UploadFeedbackForm.IMPORT_TYPE_ALL, UploadFeedbackForm.IMPORT_TYPE_FEATURE_REQUESTS):
                            fr = self.create_feature_request(row)
                            self.create_fr_themes(row, fr)
                            self.create_fr_feedback_votes(row, fr)
                        else:
                            fr = None

                        company = self.create_company(row)
                        user = self.create_user(row, company)

                        feedback = self.create_feedback(row, fr, user)
                        self.create_feedback_themes(row, feedback)
                self.fix_feature_request_created()
        self.send_results_email()

    def send_results_email(self):
        subject = f"Finished import for {self.customer.name}"

        problem_text = ""
        for problem in self.problems:
            problem_text += f"{problem}\n"

        invalid_text = ""
        for invalid_row in self.invalid_rows:
            invalid_text += f"{invalid_row}\n"

        message = f"""
Problems:
{problem_text}

Total feature requests imported:
{self.total_fr_imported}

Total feedback imported:
{self.total_feedback_imported}

Total companies:
{self.total_companies_imported}

Total users:
{self.total_users_imported}

Total tags:
{self.total_themes_imported}

Import token:
{self.import_token}

Invalid rows:
{invalid_text}
"""
        mail_admins(subject, message, html_message=None)


    # Set the created date for newly imported FRs to the date of the oldest
    # related Feedback
    def fix_feature_request_created(self):
        new_feature_requests = FeatureRequest.objects.filter(
            customer=self.customer,
            import_token=self.import_token)

        for fr in new_feature_requests:
            feedbacks = fr.feedback_set.all().order_by("created")
            if feedbacks.exists():
                # Workaround for setting created b/c of autonow
                # https://stackoverflow.com/a/11316645/457884
                FeatureRequest.objects.filter(
                    customer=self.customer,
                    pk=fr.pk).update(created=feedbacks[0].created)

    def create_feature_request(self, row):
        defaults = {
            'description': html2text(row['fr_description']),
            'state': row['fr_state'],
            'priority': row['fr_priority'],
            'import_token': self.import_token,
        }
        fr, created = FeatureRequest.objects.get_or_create(
            customer=self.customer,
            title=html2text(row['fr_title'].strip()),
            defaults=defaults)
        if created:
            self.total_fr_imported += 1
        return fr

    def create_fr_feedback_votes(self, row, feature_request):
        defaults = {
            'import_token': self.import_token,
            'source_username': 'Savio Admin Importer'
        }

        votes = row.get('fr_votes', 0)
        for vote in range(int(votes)):
            vote_id = str(uuid.uuid4())
            feedback, created = Feedback.objects.get_or_create(
                customer=self.customer,
                problem=f"Vote import placeholder {vote_id}",
                feature_request=feature_request,
                state=Feedback.ARCHIVED,
                defaults=defaults,
            )

    def create_fr_themes(self, row, feature_request):
        if 'fr_tags' in row.keys():
            themes = row['fr_tags'].split(",")
            for theme_name in themes:
                theme_name = theme_name.strip()
                if theme_name:
                    defaults = {
                        'title': theme_name,
                        'import_token': self.import_token,
                    }

                    theme, created = Theme.objects.get_or_create(
                        customer=self.customer,
                        title__iexact=theme_name,
                        defaults=defaults)
                    feature_request.themes.add(theme)
                    if created:
                        self.total_themes_imported += 1


    def create_feedback_themes(self, row, feedback):
        if 'feedback_tags' in row.keys():
            themes = row['feedback_tags'].split(",")
            for theme_name in themes:
                theme_name = theme_name.strip()
                if theme_name:
                    defaults = {
                        'title': theme_name,
                        'import_token': self.import_token,
                    }

                    theme, created = Theme.objects.get_or_create(
                        customer=self.customer,
                        title__iexact=theme_name,
                        defaults=defaults)
                    feedback.themes.add(theme)
                    if created:
                        self.total_themes_imported += 1


    def create_company(self, row):
        if 'company_name' in row.keys() and row['company_name'].strip():
            defaults = {
                'import_token': self.import_token,
            }
            filterable_attributes = {}
            try:
                monthly_spend = float(row['company_fa_monthly_spend'])
                filterable_attributes['monthly_spend'] = monthly_spend
            except ValueError:
                pass

            plan = row.get('company_fa_plan', '').strip()
            if plan:
                filterable_attributes['plan'] = plan

            defaults['filterable_attributes'] = filterable_attributes

            internal_id = row['company_internal_id'].strip() or None
            company_name = textify_html(row['company_name'].strip())
            try:
                # This is a bit tricky and maybe not perfect.
                # If we've got an interal_id assume it's right
                # and JUST use it to look up companies.
                # This avoids issues where the name is subtly
                # different like 'Carolina Sun Heating &amp; Air'
                # and 'Carolina Sun Heating & Air'
                kwargs = {
                    'customer': self.customer,
                    'defaults': defaults,
                }

                if internal_id:
                    kwargs['internal_id'] = internal_id
                else:
                    kwargs['name'] = company_name


                print(kwargs)
                company, created = AppCompany.objects.get_or_create(**kwargs)
                if created:
                    self.total_companies_imported += 1

            except AppCompany.MultipleObjectsReturned:
                company = AppCompany.objects.filter(
                                    customer=self.customer,
                                    name=company_name)[0]
        else:
            company = None
        return company

    def create_user(self, row, company):
        user = None
        if 'user_email' in row.keys() and row['user_email'].strip():
            defaults = {
                'import_token': self.import_token,
            }
            if company:
                defaults['company'] = company

            if row['user_name']:
                defaults['name'] = row['user_name']

            if row['user_internal_id'].strip():
                defaults['internal_id'] = row['user_internal_id'].strip()

            user, created = AppUser.objects.get_or_create(
                customer=self.customer,
                email=row['user_email'].strip(),
                defaults=defaults)

            if created:
                self.total_users_imported += 1

        return user

    def create_feedback(self, row, feature_request, user):
        feedback = None
        if row.get('feedback_problem', '').strip():
            defaults = {
                'import_token': self.import_token,
                'source_username': 'Savio Admin Importer'
            }

            if user:
                defaults['user'] = user
            if row['feedback_source_url']:
                defaults['source_url'] = row['feedback_source_url']

            feedback_state = row.get('feedback_state', Feedback.ARCHIVED)
            feedback, created = Feedback.objects.get_or_create(
                customer=self.customer,
                problem=html2text(row['feedback_problem'].strip()),
                feature_request=feature_request,
                state=feedback_state,
                defaults=defaults,
            )
            if created:
                self.total_feedback_imported += 1

            # Workaround for setting created b/c of autonow
            # https://stackoverflow.com/a/11316645/457884
            if 'feedback_created' in row.keys() and row['feedback_created'].strip():
                formats_to_try = (
                    "%m/%d/%Y",
                    "%Y-%m-%d %H:%M",
                    "%Y-%m-%d %H:%M:%S",
                )

                created = None
                for format in formats_to_try:
                    try:
                        created = datetime.datetime.strptime(row['feedback_created'], format).date()
                    except ValueError:
                        pass
                if not created:
                    raise Exception(f"Couldn't convert {row['feedback_created']} to a valid date")

                Feedback.objects.filter(
                    customer=self.customer,
                    pk=feedback.pk).update(created=created)
        return feedback

    def validate_required_columms(self, columns):
        problems = []
        required_columns = (
            'user_email',
            'user_name',
            'user_internal_id',
            'company_name',
            'company_internal_id',
            'company_fa_plan',
            'company_fa_monthly_spend',
            'fr_title',
            'fr_state',
            'fr_priority',
            'fr_description',
            'fr_tags',
            'feedback_problem',
            'feedback_tags',
            'feedback_created',
            'feedback_source_url',
        )

        for required_column in required_columns:
            if required_column not in columns:
                problems.append(f"Required column '{required_column}' missing.")
        return problems

    def validate_row(self, row, import_type):
        reasons = list()

        # Feedback related
        has_valid_feedback_problem = row['feedback_problem'].strip()
        has_valid_feedback_created = row['feedback_created'].strip()
        if not has_valid_feedback_problem:
            reasons.append("feedback_problem can't be blank")
        if not has_valid_feedback_created:
            reasons.append("feedback_created can't be blank")

        # Feature Request realate
        has_valid_title, reason_title = self.valid_title(row)
        has_valid_state, reason_state = self.valid_state(row)
        has_valid_priority, reason_priority = self.valid_priority(row)
        if not has_valid_title:
            reasons.append(reason_title)
        if not has_valid_state:
            reasons.append(reason_state)
        if not has_valid_priority:
            reasons.append(reason_priority)

        if import_type == UploadFeedbackForm.IMPORT_TYPE_ALL:
            valid = all((
                has_valid_feedback_created,
                has_valid_feedback_created,
                has_valid_title,
                has_valid_state,
                has_valid_priority,
                )
            )
        elif import_type == UploadFeedbackForm.IMPORT_TYPE_FEATURE_REQUESTS:
            valid = all((
                has_valid_title,
                has_valid_state,
                has_valid_priority,
                )
            )
        elif import_type == UploadFeedbackForm.IMPORT_TYPE_FEEDBACK: 
            valid = all((
                has_valid_feedback_created,
                has_valid_feedback_created,
                )
            )
        else:
            raise Exception("Invalid import type")

        if not valid:
            row_name = row['fr_title'] or row['feedback_problem'] or "N/A"
            self.invalid_rows.append((row_name, reasons))

        return valid

    def valid_title(self, row):
        if 'fr_title' not in row.keys():
            valid = False
            reason = "Missing title"        
        elif row['fr_title'].strip() == "":            
            valid = False
            reason = "Title can't be blank."
        else:
            valid = True
            reason = None
        return (valid, reason)
    
    def valid_state(self, row):
        if 'fr_state' in row.keys():
            valid = row['fr_state'].upper() in FeatureRequest.STATE_KEYS
            reason = f"Invalid state '{row['fr_state']}'."
        else:
            valid = True
            reason = None
        return (valid, reason)

    def valid_priority(self, row):
        if 'fr_priority' in row.keys():
            valid_priorities = list(FeatureRequest.PRIORITY_KEYS)
            valid_priorities.append("")
            valid = row['fr_priority'].upper() in valid_priorities
            reason = f"Invalid priority '{row['fr_priority']}'."
        else:
            valid = True
            reason = None
        return (valid, reason)
