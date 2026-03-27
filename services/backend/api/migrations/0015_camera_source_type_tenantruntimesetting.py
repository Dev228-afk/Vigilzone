from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0014_invitation_public_id_compat"),
    ]

    operations = [
        migrations.AddField(
            model_name="camera",
            name="source_type",
            field=models.CharField(
                choices=[("registered", "Registered"), ("webcam", "Webcam")],
                default="registered",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="TenantRuntimeSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("webcam_enabled", models.BooleanField(default=False)),
                (
                    "tenant",
                    models.OneToOneField(on_delete=models.CASCADE, related_name="runtime_settings", to="api.tenant"),
                ),
            ],
        ),
    ]
