"""
Add production audit fields to KnownEntityEmbedding and an index for active embeddings.

Phase 5 of the Entity Registration and Processing Plan.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0007_camera_entity_detection_enabled_and_tenantruntime_identity_runtime_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="knownentityembedding",
            name="is_active",
            field=models.BooleanField(
                default=True,
                help_text="Mark stale embeddings inactive on re-enrollment rather than hard-deleting.",
            ),
        ),
        migrations.AddField(
            model_name="knownentityembedding",
            name="quality_score",
            field=models.FloatField(
                blank=True,
                help_text="Optional quality metric from the embedding pipeline (0.0-1.0).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="knownentityembedding",
            name="embedding_model",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Model used to generate this embedding (e.g. insightface/buffalo_l, clip/ViT-B-32).",
                max_length=128,
            ),
        ),
        migrations.AddField(
            model_name="knownentityembedding",
            name="embedding_version",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Tracks re-embedding generations for delta-sync.",
            ),
        ),
        migrations.AddField(
            model_name="knownentityembedding",
            name="source_image_uri",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Reference back to the KnownEntityAsset used to generate this embedding.",
                max_length=1024,
            ),
        ),
        migrations.AddField(
            model_name="knownentityembedding",
            name="source_checksum",
            field=models.CharField(
                blank=True,
                default="",
                help_text="SHA-256 checksum of the source image for integrity verification.",
                max_length=128,
            ),
        ),
        migrations.AddField(
            model_name="knownentityembedding",
            name="generated_by",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Origin of this embedding: 'ai_enrollment', 'backend_worker', etc.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="knownentityembedding",
            name="deleted_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Soft-delete timestamp for audit trail.",
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name="knownentityembedding",
            index=models.Index(
                fields=["entity", "is_active"],
                name="api_ke_entity_active_idx",
            ),
        ),
    ]
