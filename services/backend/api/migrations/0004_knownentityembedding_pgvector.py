from django.db import migrations, models
import django.db.models.deletion
from pgvector.django import VectorExtension, VectorField


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0003_fix_airuntimeregistration_bootstrap_fn"),
    ]

    operations = [
        VectorExtension(),
        migrations.CreateModel(
            name="KnownEntityEmbedding",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "modality",
                    models.CharField(
                        choices=[("face", "Face"), ("pet_clip", "Pet CLIP")],
                        max_length=32,
                    ),
                ),
                ("vector", VectorField(dimensions=512)),
                ("source_dim", models.PositiveIntegerField(default=512)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "entity",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="embeddings",
                        to="api.knownentity",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entity_embeddings",
                        to="api.tenant",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["tenant", "modality"],
                        name="api_ke_tenant_mod_idx",
                    ),
                    models.Index(
                        fields=["entity", "modality"],
                        name="api_ke_entity_mod_idx",
                    ),
                ],
            },
        ),
    ]
