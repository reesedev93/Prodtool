# Generated by Django 2.1.3 on 2019-08-03 20:01

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('feedback', '0023_auto_20190702_2245'),
    ]

    operations = [
        migrations.AddField(
            model_name='featurerequest',
            name='import_token',
            field=models.CharField(blank=True, help_text='Used to keep track of all of the items created in a single admin import for easy deletion in case of disaster.', max_length=36),
        ),
    ]
