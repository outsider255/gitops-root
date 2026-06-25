import urllib.request
import urllib.parse
import urllib.error
import os
import asyncio
import json

from fastapi.concurrency import run_in_threadpool
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

NAMESPACE = "render-service"
ASSET_LIBRARY_BASE = "http://asset-library-service.render-service.svc.cluster.local"
ONEDRIVE_FRAGMENT_SIZE = 10 * 1024 * 1024
JOBS = {}


def resolve_asset_path(kind: str, asset_id: str) -> str:
    """Looks up an asset's real file_path from the asset-library DB by id.
    Assets aren't necessarily named after their db id (e.g. Mode A names
    motion-converted loops after the source still's job id, not the db id
    asset-library assigns on insert), so this can't be guessed from a
    fixed naming convention -- it must be looked up."""
    with urllib.request.urlopen(f"{ASSET_LIBRARY_BASE}/{kind}/{asset_id}", timeout=10) as resp:
        return json.loads(resp.read())["file_path"]


def k8s_job_name(prefix: str, job_id: str) -> str:
    """job_id values (loop_xxx, trk_xxx, motionconvert-loop_xxx, ...) may
    contain underscores, which are not valid in K8s resource names (RFC 1123
    subdomain). Sanitize so create_namespaced_job doesn't 422."""
    return f"{prefix}-{job_id}".replace("_", "-").lower()


def job_phase_from_status(job_status) -> str:
    """Pure helper: maps a K8s V1JobStatus-like object to one of
    queued/running/completed/failed using status.conditions as the
    source of truth, NOT the status.failed/status.succeeded counters
    (kubernetes-client/python#1766: status.failed can be None even on
    a genuinely failed Job).
    """
    conditions = getattr(job_status, "conditions", None) or []
    for cond in conditions:
        cond_type = getattr(cond, "type", None)
        cond_status = getattr(cond, "status", None)
        if cond_type == "Complete" and cond_status == "True":
            return "completed"
        if cond_type == "Failed" and cond_status == "True":
            return "failed"
    if getattr(job_status, "active", None):
        return "running"
    return "queued"


def get_job_phase(job_name: str) -> str:
    config.load_incluster_config()
    batch = client.BatchV1Api()
    job = batch.read_namespaced_job_status(name=job_name, namespace=NAMESPACE)
    return job_phase_from_status(job.status)


def build_assembly_job_spec(job) -> "client.V1Job":
    """Builds the real ffmpeg assembly Job spec. Resolves loop_ids/track_ids
    to their real /assets file paths via the Asset Library (see
    resolve_asset_path) since assets aren't reliably named after their db id."""
    job_name = k8s_job_name("assemble", job.job_id)
    loop_path = resolve_asset_path("loops", job.loop_ids[0])
    track_paths = [resolve_asset_path("tracks", track_id) for track_id in job.track_ids]
    container = client.V1Container(
        name="assemble",
        image="render-service:v19",
        command=["python3", "/app/assembly_entrypoint.py"],
        args=[loop_path, job.category, job.output_path, *track_paths],
        volume_mounts=[
            client.V1VolumeMount(name="outbox", mount_path="/outbox"),
            client.V1VolumeMount(name="assets", mount_path="/assets"),
        ],
    )
    pod_template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"job-id": job.job_id}),
        spec=client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
            volumes=[
                client.V1Volume(
                    name="outbox",
                    persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name="render-outbox-pvc"),
                ),
                client.V1Volume(
                    name="assets",
                    persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name="binary-assets-pvc"),
                ),
            ],
        ),
    )
    return client.V1Job(
        metadata=client.V1ObjectMeta(name=job_name),
        spec=client.V1JobSpec(
            template=pod_template,
            backoff_limit=2,
            ttl_seconds_after_finished=3600,
        ),
    )


def create_job_idempotent(batch, job_spec) -> str:
    """n8n's HTTP client occasionally drops a response on a slow/idle
    connection and silently retries the same POST -- since job names are
    deterministic from job_id, the retry's create call 409s on a job that
    was already created by the first (lost-response) attempt. Treat 409
    as success instead of surfacing a spurious failure."""
    try:
        batch.create_namespaced_job(namespace=NAMESPACE, body=job_spec)
    except ApiException as e:
        if e.status != 409:
            raise
    return job_spec.metadata.name


def _dispatch_assembly_job_sync(job) -> str:
    config.load_incluster_config()
    batch = client.BatchV1Api()
    job_spec = build_assembly_job_spec(job)
    return create_job_idempotent(batch, job_spec)


async def dispatch_assembly_job(job) -> str:
    return await run_in_threadpool(_dispatch_assembly_job_sync, job)


async def watch_assembly_job_for_webhook(job):
    """Background task: polls the already-dispatched Job purely so the
    resume_url webhook can be fired once the Job reaches a terminal phase."""
    job_name = k8s_job_name("assemble", job.job_id)
    phase = "queued"
    while phase not in ("completed", "failed"):
        try:
            phase = await run_in_threadpool(get_job_phase, job_name)
        except ApiException as e:
            JOBS[job.job_id]["webhook_notified"] = False
            JOBS[job.job_id]["webhook_error"] = str(e)
            return
        if phase in ("completed", "failed"):
            break
        await asyncio.sleep(2)

    if phase == "completed":
        JOBS[job.job_id]["output_path"] = job.output_path

    if job.resume_url:
        try:
            urllib.request.urlopen(job.resume_url, timeout=10)
            JOBS[job.job_id]["webhook_notified"] = True
        except Exception as e:
            JOBS[job.job_id]["webhook_notified"] = False
            JOBS[job.job_id]["webhook_error"] = str(e)


def build_clip_job_spec(req) -> "client.V1Job":
    job_name = k8s_job_name("clip", req.job_id)
    container = client.V1Container(
        name="clip",
        image="render-service:v19",
        command=["python3", "/app/clip_entrypoint.py"],
        args=[
            req.main_loop_path, req.main_track_path,
            str(req.audio_start_s), str(req.audio_duration_s),
            req.output_path,
        ],
        volume_mounts=[
            client.V1VolumeMount(name="outbox", mount_path="/outbox"),
            client.V1VolumeMount(name="assets", mount_path="/assets"),
        ],
    )
    pod_template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"job-id": req.job_id}),
        spec=client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
            volumes=[
                client.V1Volume(name="outbox", persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name="render-outbox-pvc")),
                client.V1Volume(name="assets", persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name="binary-assets-pvc")),
            ],
        ),
    )
    return client.V1Job(
        metadata=client.V1ObjectMeta(name=job_name),
        spec=client.V1JobSpec(template=pod_template, backoff_limit=2, ttl_seconds_after_finished=3600),
    )


async def dispatch_clip_job(req) -> str:
    def _sync():
        config.load_incluster_config()
        batch = client.BatchV1Api()
        spec = build_clip_job_spec(req)
        return create_job_idempotent(batch, spec)
    return await run_in_threadpool(_sync)


async def watch_clip_job(req):
    job_name = k8s_job_name("clip", req.job_id)
    phase = "queued"
    while phase not in ("completed", "failed"):
        try:
            phase = await run_in_threadpool(get_job_phase, job_name)
        except ApiException:
            return
        if phase in ("completed", "failed"):
            break
        await asyncio.sleep(2)
    JOBS[req.job_id]["status"] = phase
    if phase == "completed":
        JOBS[req.job_id]["output_path"] = req.output_path


def build_motion_convert_job_spec(job_id: str, still_path: str, output_path: str, orientation: str = "horizontal") -> "client.V1Job":
    output_w, output_h = (1080, 1920) if orientation == "vertical" else (1920, 1080)
    job_name = k8s_job_name("job", job_id)
    container = client.V1Container(
        name="motion-convert",
        image="render-service:v19",
        command=["python3", "-c", (
            "import ffmpeg_assembly as fa, subprocess, sys; "
            "subprocess.run(fa.build_ken_burns_cmd(sys.argv[1], sys.argv[2], zoom_target=1.0, "
            "output_w=int(sys.argv[3]), output_h=int(sys.argv[4])), check=True)"
        )],
        args=[still_path, output_path, str(output_w), str(output_h)],
        volume_mounts=[client.V1VolumeMount(name="assets", mount_path="/assets")],
    )
    pod_template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"job-id": job_id}),
        spec=client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
            volumes=[client.V1Volume(
                name="assets",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name="binary-assets-pvc"),
            )],
        ),
    )
    return client.V1Job(
        metadata=client.V1ObjectMeta(name=job_name),
        spec=client.V1JobSpec(template=pod_template, backoff_limit=2, ttl_seconds_after_finished=3600),
    )


async def dispatch_motion_convert_job(job_id: str, still_path: str, output_path: str, orientation: str = "horizontal") -> str:
    def _sync():
        config.load_incluster_config()
        batch = client.BatchV1Api()
        spec = build_motion_convert_job_spec(job_id, still_path, output_path, orientation)
        return create_job_idempotent(batch, spec)
    return await run_in_threadpool(_sync)


async def watch_motion_convert_job(job_id: str, output_path: str):
    job_name = k8s_job_name("job", job_id)
    phase = "queued"
    while phase not in ("completed", "failed"):
        try:
            phase = await run_in_threadpool(get_job_phase, job_name)
        except ApiException as e:
            JOBS[job_id]["error"] = str(e)
            return
        if phase in ("completed", "failed"):
            break
        await asyncio.sleep(2)
    JOBS[job_id]["status"] = phase
    if phase == "completed":
        JOBS[job_id]["output_path"] = output_path


def upload_youtube_sync(req, access_token: str) -> str:
    """Streams the file straight from disk to YouTube's resumable upload
    endpoint -- never buffers the whole (multi-GB, for a 2hr video) file
    in memory. Runs in the render-service pod itself (no separate K8s
    Job needed, this is I/O-bound not CPU-bound). access_token is passed
    in separately (from the Authorization header n8n's predefinedCredentialType
    HTTP node attaches) rather than carried on req, so it's never a field
    on a model that gets logged/persisted anywhere."""
    init_body = json.dumps({
        "snippet": {"title": req.title, "description": req.description, "categoryId": req.category_id},
        "status": {"privacyStatus": req.privacy_status},
    }).encode()
    init_req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=init_body,
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(init_req, timeout=30) as resp:
            upload_url = resp.headers["Location"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"YouTube init session failed ({e.code}): {e.read().decode(errors='replace')}") from e

    size = os.path.getsize(req.file_path)
    with open(req.file_path, "rb") as f:
        put_req = urllib.request.Request(
            upload_url,
            data=f,
            method="PUT",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "video/mp4",
                "Content-Length": str(size),
            },
        )
        try:
            with urllib.request.urlopen(put_req, timeout=3600) as resp:
                return json.loads(resp.read())["id"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"YouTube upload PUT failed ({e.code}): {e.read().decode(errors='replace')}") from e


async def upload_youtube(req, access_token: str):
    JOBS[req.job_id]["status"] = "running"
    try:
        video_id = await run_in_threadpool(upload_youtube_sync, req, access_token)
        JOBS[req.job_id]["status"] = "completed"
        JOBS[req.job_id]["video_id"] = video_id
        JOBS[req.job_id]["youtube_video_url"] = f"https://youtube.com/watch?v={video_id}"
    except Exception as e:
        JOBS[req.job_id]["status"] = "failed"
        JOBS[req.job_id]["error"] = str(e)


def upload_onedrive_sync(req, access_token: str) -> dict:
    """OneDrive's upload-session PUTs must be chunked into fragments
    (Microsoft Graph rejects very large single-shot PUTs) -- reads
    ONEDRIVE_FRAGMENT_SIZE bytes at a time, so memory use stays flat
    regardless of file size."""
    safe_target = urllib.parse.quote(req.target_path)
    init_req = urllib.request.Request(
        f"https://graph.microsoft.com/v1.0/me/drive/root:/{safe_target}:/createUploadSession",
        data=b"{}",
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(init_req, timeout=30) as resp:
            upload_url = json.loads(resp.read())["uploadUrl"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OneDrive init session failed ({e.code}): {e.read().decode(errors='replace')}") from e

    size = os.path.getsize(req.file_path)
    result = None
    with open(req.file_path, "rb") as f:
        start = 0
        while start < size:
            chunk = f.read(ONEDRIVE_FRAGMENT_SIZE)
            end = start + len(chunk) - 1
            frag_req = urllib.request.Request(
                upload_url,
                data=chunk,
                method="PUT",
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                },
            )
            try:
                with urllib.request.urlopen(frag_req, timeout=120) as resp:
                    body = resp.read()
                    if body:
                        result = json.loads(body)
            except urllib.error.HTTPError as e:
                raise RuntimeError(f"OneDrive fragment PUT failed ({e.code}): {e.read().decode(errors='replace')}") from e
            start = end + 1
    return result


async def upload_onedrive(req, access_token: str):
    JOBS[req.job_id]["status"] = "running"
    try:
        result = await run_in_threadpool(upload_onedrive_sync, req, access_token)
        JOBS[req.job_id]["status"] = "completed"
        JOBS[req.job_id]["onedrive_result"] = result
    except Exception as e:
        JOBS[req.job_id]["status"] = "failed"
        JOBS[req.job_id]["error"] = str(e)
