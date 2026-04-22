import os
import django
import sys

# Set up Django environment
sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")
django.setup()

from api.models import KnownEntity, KnownEntityProcessingJob, OutboxEvent, KnownEntityEmbedding

print("--- Known Entities (Recent 10) ---")
for ent in KnownEntity.objects.all().order_by("-id")[:10]:
    print(f"ID={ent.id}, Name={ent.name}, Status={ent.status}, Version={ent.embedding_version}")

print("\n--- Recent Processing Jobs (Last 10) ---")
for job in KnownEntityProcessingJob.objects.all().order_by("-id")[:10]:
    print(f"ID={job.id}, EntityID={job.entity_id}, Status={job.status}, Finished={job.finished_at}")

print("\n--- Unpublished Outbox Events ---")
print(f"Count: {OutboxEvent.objects.filter(published_at__isnull=True).count()}")

print("\n--- Embeddings in DB ---")
print(f"Total Active Embeddings: {KnownEntityEmbedding.objects.filter(is_active=True).count()}")
