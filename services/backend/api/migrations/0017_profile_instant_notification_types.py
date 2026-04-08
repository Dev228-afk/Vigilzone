from django.db import migrations, models


def default_types():
    return ["robbery", "stranger", "fire", "intrusion", "other"]


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0016_profile_instant_notification_levels"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="instant_notification_types",
            field=models.JSONField(blank=True, default=default_types),
        ),
    ]
