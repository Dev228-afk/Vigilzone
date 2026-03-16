from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0010_camera_ingress_id_camera_ingress_rtmp_url_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="camera",
            name="ingress_id",
        ),
        migrations.RemoveField(
            model_name="camera",
            name="ingress_rtmp_url",
        ),
        migrations.RemoveField(
            model_name="camera",
            name="ingress_stream_key",
        ),
        migrations.RemoveField(
            model_name="camera",
            name="livekit_room",
        ),
        migrations.RemoveField(
            model_name="camera",
            name="relay_last_error",
        ),
        migrations.RemoveField(
            model_name="camera",
            name="relay_status",
        ),
    ]
