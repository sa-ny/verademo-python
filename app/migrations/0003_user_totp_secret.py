# Generated by Django 4.2.13 on 2024-06-27 13:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0002_delete_blabber'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='totp_secret',
            field=models.CharField(max_length=100, null=True),
        ),
    ]
