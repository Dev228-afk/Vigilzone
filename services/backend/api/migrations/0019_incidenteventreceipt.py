"""
Migration to add IncidentEventReceipt model for idempotent AI event processing.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0018_remove_profile_instant_notification_types_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="IncidentEventReceipt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "event_id",
                    models.CharField(db_index=True, max_length=255, unique=True),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[("redis", "Redis"), ("webhook", "Webhook")],
                        max_length=16,
                    ),
                ),
                (
                    "processed_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "incident",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="event_receipts",
                        to="api.incident",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["event_id"],
                        name="api_inciden_event_i_idx",
                    ),
                ],
            },
        ),
    ]
