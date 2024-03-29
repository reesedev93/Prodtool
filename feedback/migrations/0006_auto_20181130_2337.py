# Generated by Django 2.1.3 on 2018-11-30 23:37

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('feedback', '0005_feedback_snooze_till'),
    ]

    operations = [
        migrations.AlterField(
            model_name='feedback',
            name='raw_content',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='feedback',
            name='remote_id',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='feedback',
            name='source',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='feedback.FeedbackImporter'),
        ),
        migrations.AlterField(
            model_name='feedback',
            name='title',
            field=models.CharField(blank=True, max_length=1024),
        ),
    ]
