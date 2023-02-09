# Generated by Django 2.1.3 on 2019-10-01 23:24

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('feedback', '0028_auto_20190923_1929'),
    ]

    operations = [
        migrations.AlterField(
            model_name='featurerequest',
            name='state',
            field=models.CharField(choices=[('UNTRIAGED', 'Untriaged'), ('UNDER_CONSIDERATION', 'Under Consideration'), ('PLANNED', 'Planned'), ('IN_PROGRESS', 'In Progress'), ('SHIPPED', 'Shipped'), ('WONT_DO', "Won't do")], default='UNTRIAGED', max_length=30),
        ),
    ]
