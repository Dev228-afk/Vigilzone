from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0011_alert_tenant_alter_alert_unique_together_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="airuntimeregistration",
            name="desired_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
