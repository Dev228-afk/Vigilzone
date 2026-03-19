from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0011_remove_legacy_livekit_relay_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="knownentity",
            name="cameras",
            field=models.ManyToManyField(blank=True, related_name="known_entities", to="api.camera"),
        ),
        migrations.AddField(
            model_name="knownentity",
            name="last_camera",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="last_seen_entities", to="api.camera"),
        ),
    ]
