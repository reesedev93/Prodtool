# Generated by Django 2.1.3 on 2019-01-24 01:12

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('feedback', '0008_auto_20190124_0106'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='feedback',
            unique_together={('customer', 'remote_id', 'source')},
        ),
    ]