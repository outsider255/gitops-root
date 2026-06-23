# Shared Asset Storage Contract

This is the single source of truth for the shared binary-asset path convention
used by both the Asset Library service and render-service/render-worker Jobs.
Both services MUST read/write this contract exactly as documented — no path
translation layer exists or should be introduced.

## PVC

- **Name:** `binary-assets-pvc`
- **Namespace:** `render-service` (single consolidated namespace per D-12; Asset
  Library and render-service both run here)
- **Access mode:** `ReadWriteOnce` (single-node K3s — no RWX/NFS/Longhorn, per D-02)
- **Mount path:** `/assets`, identical in both the Asset Library pod and every
  render-worker Job pod

## Locked `file_path` convention

Values stored in `track_library.file_path` and `visual_loop_library.file_path`
MUST follow:

```
/assets/<type>/<id>.<ext>
```

- `<type>` — asset category subdirectory, e.g. `loops`, `tracks`
- `<id>` — the library row id
- `<ext>` — the file extension

**Examples:**
- `/assets/loops/42.mp4`
- `/assets/tracks/17.mp3`

Both services construct and consume this exact path with no translation
between the value stored in SQLite and the path used on disk inside the
container — what's in `file_path` is exactly what's mounted at `/assets`.

## Why this matters

This contract is what Plan 03's Asset Library upload rewrite and read-back
Job proof verify against (PLUMB-01). Treating `file_path` as an ambiguous
convention instead of a locked contract was flagged as an anti-pattern during
Phase 1 research — this document exists so both services reference one
definition, not two independently-evolving assumptions.
