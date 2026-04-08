from django.db import migrations, models


def default_levels():
    return ["critical", "severe", "moderate"]


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0015_camera_source_type_tenantruntimesetting"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="instant_notification_levels",
            field=models.JSONField(blank=True, default=default_levels),
        ),
    ]
