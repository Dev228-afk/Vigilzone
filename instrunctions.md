Role

You are the system architect + senior computer vision engineer. You will modify the existing codebase (see attached zip) to fix:

Entity enrollment via file upload is unreliable (live capture works).

Temporal verifier X3D-S fails with kernel-size error: T=5 H=W=7.

Too many false positives in unknown anomaly + candidate lanes.

Do this with minimal disruption: preserve existing APIs when possible, but you may add new ones if the new workflow is more robust.

A) Entity upload enrollment — replace with robust staging workflow (and keep legacy)
A1) Implement “staging upload → enroll by reference” (mandatory)

The core fix is: never compute embeddings directly from UploadFile streams. Always persist first, then process from disk.

New endpoints (required)

POST /uploads/enroll_images

multipart files[]

Create upload_id = upl_<uuid>

Save to: data/staging_uploads/<upload_id>/<idx>_<safe_name>.jpg

Return:

{"upload_id":"upl_...","stored":[{"filename":"0_x.jpg","url":"/staging/upl_.../0_x.jpg"}]}

POST /entities/enroll_person_from_upload

JSON body: {upload_id, name, role, metadata_json?}

Load all images from disk

Extract face embeddings

Save same images into: data/enroll_images/<entity_id>/...

Store embeddings and metadata

POST /identity/reload (or call internal reload)

Delete staging folder on success (configurable)

POST /entities/enroll_pet_from_upload

Same as person but pet embedder

Static file serving (required)

GET /staging/{upload_id}/{filename} to serve staging thumbnails for UI preview

GET /enroll_images/{entity_id}/{filename} to serve enrolled images

Validation rules (required)

If 0 valid faces found across all images → reject enrollment with reason + list of images that failed.

Require min_images good embeddings (config default 3).

Return saved_images_count and saved_filenames in response.

A2) Hardening the existing legacy endpoints (optional but recommended)

For /entities/enroll_person and /entities/enroll_pet:

Internally route through staging:

save files → call the same enroll-from-upload logic
This preserves backwards compatibility and fixes the bug.

A3) UI changes (required)

Entities tab must use the new workflow:

Step 1: upload images → show preview thumbnails from /staging/...

Step 2: click “Enroll Person/Pet” → calls /entities/*_from_upload

Show server response including entity_id and links to enrolled images.

B) Temporal verifier X3D-S error — fix clip construction + preprocessing (mandatory)

Your error:
input image (T: 5 H: 7 W: 7) smaller than kernel size (kT: 13 kH: 5 kW: 5)
This means you are feeding a too-short clip and likely feeding features or downsampled tensors (7x7 spatial) rather than raw frames.

B1) Temporal verifier must accept RAW FRAMES ONLY (required)

Refactor TemporalVerifier interface to accept:

frames_bgr: List[np.ndarray] (raw images)

fps: float
Return:

confirmed: bool, score: float, debug: {input_shape, clip_len, used_padding}

Do not pass feature maps to X3D. Pass frames.

B2) Enforce minimum clip length and size (required)

Set these defaults:

clip_len = 16

output frame size for model: 224x224

If ring buffer returns fewer than 16 frames: pad by repeating last frame until 16.

If frames are too small: resize to 224x224.

B3) Correct tensor format for X3D (required)

Convert frames to tensor:

BGR → RGB

float32 in [0,1]

normalize (mean/std; can be standard Kinetics values or a simple ImageNet normalization)

tensor shape must be: (1, 3, T, 224, 224) where T=16

Log one line per run:
TemporalVerifier input tensor: (1,3,16,224,224) device=cuda:0

B4) Ring buffer extraction must support 16 frames (required)

Even if temporal verifier runs at low cadence, the ring buffer must store enough frames:

Ensure ring buffer capture rate is >= 10 fps (already present).

Clip extraction: take last 16 frames spaced by sample_rate (default 1).

Provide sample_rate in config, but keep default simple.

B5) Fallback logic change (required)

Only fall back to stub if:

model load fails, OR

preprocessing fails unexpectedly
Not because clip is too small (you must pad/resize).

Acceptance:

That kernel-size error must never occur again.

C) Reduce false positives (system-wide) — implement “context-aware suppression” + better gating

Your current system over-alerts because:

anomaly stub relies on motion energy

candidate lanes are permissive

there’s not enough “explainable suppression” using identity + zones + time

C1) Add a suppression layer BEFORE emitting any severe alert (required)

Implement policy.suppress(alert_type, context) -> bool with rules:

Unknown anomaly suppression (must)

Suppress UNKNOWN_SEVERE_ANOMALY if:

Motion is explained by:

KNOWN_PERSON with allowed role in allowed zone/time

PET (known pet)

Global exposure change:

too much of the frame changes at once (auto-exposure)

Periodic motion:

fan/trees-like repeating pattern

C2) Improve motion stub gating (required)

In the motion-energy anomaly stub (and any candidate lanes that use motion):
Add:

min_motion_area_ratio (ignore tiny motion)

max_global_change_ratio (ignore exposure change)

persistence: require sustained hits (e.g. 4/8) instead of 3/5 for unknown anomaly

min_interval_s_between_unknown_alerts (spam control)

C3) Zone-aware anomaly (required)

If zones exist:

compute anomaly only inside “sensitive” zones (restricted/yard)

ignore outside to cut FPs drastically

C4) Identity-driven severity applied consistently (required)

For intrusion:

UNKNOWN_PERSON in restricted zone → HIGH

KNOWN_OWNER/FAMILY in restricted → LOW or suppress (config-driven)
This reduces “false positives” that are actually correct detections but not actionable.

C5) Add “debug counters” for tuning (required)

Expose via /system/diagnostics:

counts of suppressed alerts by reason

last motion stats (area ratio, global change ratio, periodicity score)

last temporal verifier input shape and whether padding was applied

Update UI Debug tab to display these.

D) Deliverables / acceptance criteria (must all pass)

Entity upload works reliably:

/uploads/enroll_images saves files

UI previews staging images

/entities/enroll_person_from_upload enrolls and persists images and embeddings

/entities/{id}/images shows saved images

Temporal verifier works:

X3D-S never errors with kernel size

Logs show tensor (1,3,16,224,224) and device cuda:0 when GPU enabled

False positives reduced:

Unknown anomaly no longer triggers constantly for benign motion in normal scenes

Suppression reasons are visible in diagnostics/UI

Implementation constraints

Do not break existing realtime pipeline.

Do not add training.

Keep components optional/pluggable.

No hallucinated model files. If a model weight is missing and no deterministic source is configured, keep lane stub/disabled with clear message.