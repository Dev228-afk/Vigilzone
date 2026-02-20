1) Deterministic, working pretrained weights (no guessing)
1.1 Add Hugging Face auto-download support (required)

Enhance the existing Doctor/ModelResolver so that missing model files are auto-downloaded only when hf_repo_id + hf_filename are present.

Use huggingface_hub.hf_hub_download(repo_id=..., filename=...)

Store into <project_root>/models/<filename> (or the configured weights path)

Update in-memory config to the downloaded absolute path

Log: Auto-fetched <key> from HF: <repo_id>/<filename> -> <local_path>

Install dependency (document in README and add to requirements):

huggingface_hub

1.2 Provide default, known HF sources for missing lanes (in config)

Update configs/models.yaml with deterministic sources for the missing assets below.

A) Fire/Smoke YOLOv8 weights (working file on HF)

Use HF file from repo SHOU-ISD/fire-and-smoke (it hosts a YOLOv8 .pt file).

Add:

models:
  fire_smoke:
    enabled: true
    weights: "models/fire_yolov8.pt"
    hf_repo_id: "SHOU-ISD/fire-and-smoke"
    hf_filename: "yolov8n.pt"     # downloaded then saved/copied as fire_yolov8.pt
    conf: 0.30
    # IMPORTANT: class names vary by community models; must be configurable:
    class_names: ["fire", "smoke"]


Implementation requirement:

After download, copy/rename to models/fire_yolov8.pt (so the rest of the code doesn’t change).

Add safety: if class_names not found in model metadata, require class_ids and log the discovered model.names for user mapping.

B) Weapon YOLO weights (working files on HF)

Use HF repo Shantanukadam/weapon_detection, which explicitly lists model files like gun.pt, All_weapon.pt, etc.

Add (choose one default):

models:
  weapon_yolo:
    enabled: true
    weights: "models/weapon_yolov8.pt"
    hf_repo_id: "Shantanukadam/weapon_detection"
    hf_filename: "All_weapon.pt"   # broad weapon coverage
    conf: 0.35
    # must be configurable:
    class_names: ["gun", "knife", "weapon"]


Implementation requirement:

Same rename/copy to models/weapon_yolov8.pt.

Log model.names at startup and expose it in /system/diagnostics so the user can map correct class names/ids.

C) Temporal verifier (remove dependency on local x3d_s.pth)

Stop requiring models/x3d_s.pth. Use PyTorchVideo TorchHub pretrained X3D-S instead.

Update config:

models:
  temporal_verifier:
    enabled: true
    kind: "x3d"
    source: "torchhub"
    hub_repo: "facebookresearch/pytorchvideo"
    hub_model: "x3d_s"
    pretrained: true
    conf: 0.55


Implementation requirement:

In TemporalVerifier, if source=="torchhub" load via:

torch.hub.load(hub_repo, hub_model, pretrained=True)

Move model to selected torch_device.

This removes the “model not found x3d_s.pth” failure class entirely.

D) AnomalyCLIP (keep as optional; avoid fake checkpoints)

AnomalyCLIP official repo has no GitHub releases (no guaranteed downloadable checkpoint artifact).
Therefore:

Keep your current behavior: if checkpoint missing → run stub

Add an explicit “source-of-truth” policy:

only enable checkpoint loading when config provides a deterministic hf_repo_id + hf_filename (or a local file)

otherwise keep stub mode

Config:

models:
  anomalyclip:
    enabled: true
    weights: "models/anomalyclip.pt"
    hf_repo_id: ""        # user must fill (no default)
    hf_filename: ""
    sensitivity: 0.50


Implementation requirement:

If hf_repo_id is empty and file missing → log:
AnomalyCLIP disabled (no deterministic checkpoint source configured). Using motion-energy stub.
(Do NOT call it “expected” — make it an actionable requirement.)

2) Make class-mapping robust (community models vary)

For fire_smoke and weapon_yolo lanes, implement:

resolve_class_filter(model, class_names, class_ids) -> set[int]

If class_ids provided → use directly

Else if class_names provided:

build map from model.names (Ultralytics) to ids

match names case-insensitively

If mapping fails:

log discovered model.names

disable lane with clear message:
Class mapping failed. Set models.<lane>.class_ids using displayed model.names.

Expose model.names in /system/diagnostics.

3) UI: show Entity-aware information (enrollment + runtime identity)

Your UI currently doesn’t surface entity identity and enrollment workflow. Add an “Entities” section.

3.1 UI requirements (dummy webpage)

Add tabs:

Alerts

Entities

Identity Live

Entities tab (Enrollment + list)

List entities from GET /entities

Buttons:

“Enroll Person” → POST /entities/enroll_person (multipart images)

“Enroll Pet” → POST /entities/enroll_pet

“Delete” → DELETE /entities/{entity_id}

After any enroll/delete, call POST /identity/reload

Identity Live tab (debug)

Poll GET /identity/state?camera_id=... every 1–2s

Render table:

track_id, name, category, confidence, best_sim, margin, locked_until

Alerts tab (update card layout)

For each alert, show:

entity.name + entity.category + entity.confidence

show payload.identity debug (best_sim, margin, quality_ok, locked)

4) Provide Claude agent “Entity workflow context” (so it doesn’t hallucinate logic)

Add this explicit workflow as comments in code and in README:

Entity-aware workflow (runtime):

Detector produces persons/animals + track_id.

Identity lane tries face/pet crop → embedding.

Matcher compares against enrolled vectors (cosine sim).

Stabilizer converts noisy matches into stable identity per track_id (M-of-L + lock + decay).

Aggregator consumes identity for severity/suppression:

UNKNOWN_PERSON in restricted zone → HIGH

KNOWN_OWNER/FAMILY → LOW/suppress (policy-driven)

PET → suppress pet alerts

Alert JSON includes entity{...} and debug identity stats.

5) Acceptance criteria

On fresh machine with empty models folder:

Doctor auto-downloads:

fire model from SHOU-ISD/fire-and-smoke/yolov8n.pt into models/fire_yolov8.pt

weapon model from Shantanukadam/weapon_detection/All_weapon.pt into models/weapon_yolov8.pt

Temporal verifier runs without any local .pth by TorchHub X3D-S

UI shows entities list, enrollment forms, identity live table.

Alerts display entity name/category/confidence when identity is available.