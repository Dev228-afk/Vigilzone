from django.db import migrations


def update_camera_sidecar_function(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION ops.ensure_camera_sidecars(p_camera_id bigint) RETURNS void
            LANGUAGE plpgsql
            AS $$
            BEGIN
                INSERT INTO api_airuntimeregistration (
                    created_at,
                    updated_at,
                    desired_enabled,
                    desired_ingest_backend,
                    desired_sample_hz,
                    desired_lanes,
                    desired_policy_version,
                    observed_ingest_backend,
                    observed_lanes,
                    source_metadata,
                    last_error,
                    camera_id
                )
                SELECT
                    NOW(),
                    NOW(),
                    c.status = 'active',
                    'opencv',
                    2.0,
                    COALESCE(c.enabled_lanes, '[]'::jsonb),
                    1,
                    '',
                    '[]'::jsonb,
                    '{}'::jsonb,
                    '',
                    c.id
                FROM api_camera c
                WHERE c.id = p_camera_id
                ON CONFLICT (camera_id) DO NOTHING;

                INSERT INTO api_mediamtxdesiredpath (
                    created_at,
                    updated_at,
                    stream_path,
                    desired_enabled,
                    relay_mode,
                    source_uri,
                    source_kind,
                    transcode_required,
                    preview_consumer_uri,
                    ai_consumer_uri,
                    evidence_consumer_uri,
                    path_generation,
                    drift_detected,
                    last_error,
                    camera_id
                )
                SELECT
                    NOW(),
                    NOW(),
                    COALESCE(NULLIF(c.stream_path, ''), NULLIF(c.ai_camera_id, ''), 'camera-' || c.id::text),
                    c.status = 'active',
                    'relay_only',
                    COALESCE(c.rtsp_url, ''),
                    COALESCE(c.source_kind, ''),
                    FALSE,
                    '',
                    '',
                    '',
                    1,
                    FALSE,
                    '',
                    c.id
                FROM api_camera c
                WHERE c.id = p_camera_id
                ON CONFLICT (camera_id) DO NOTHING;
            END;
            $$;
            """
        )


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0002_backfillcheckpoint_schemabootstrapstate_and_more"),
    ]

    operations = [
        migrations.RunPython(
            code=update_camera_sidecar_function,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
