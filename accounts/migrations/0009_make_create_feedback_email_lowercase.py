# Generated by Django 2.1.3 on 2019-06-05 23:12

from django.db import migrations

def make_create_feedback_email_lowercase(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    for user in User.objects.all():
        # Why is this code dupped? See here:
        # https://stackoverflow.com/questions/28777338/django-migrations-runpython-not-able-to-call-model-methods/37685925#37685925
        user.create_feedback_email = user.create_feedback_email.lower()
        user.save()

class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_add_subscription'),
    ]

    operations = [
        migrations.RunPython(make_create_feedback_email_lowercase),
    ]
