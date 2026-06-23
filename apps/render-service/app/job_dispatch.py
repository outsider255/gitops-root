import urllib.request
import asyncio

from fastapi.concurrency import run_in_threadpool
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

NAMESPACE = "render-service"
JOBS = {}


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
    to /assets paths via the locked storage contract (/assets/<type>/<id>.<ext>)
    -- no separate Asset Library lookup needed inside the Job itself."""
    job_name = f"assemble-{job.job_id}"
    loop_path = f"/assets/loops/{job.loop_ids[0]}.mp4"
    track_path = f"/assets/tracks/{job.track_ids[0]}.mp3"
    container = client.V1Container(
        name="assemble",
        image="render-service:v3",
        command=["python3", "/app/assembly_entrypoint.py"],
        args=[loop_path, track_path, job.category, job.output_path],
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


def _dispatch_assembly_job_sync(job) -> str:
    config.load_incluster_config()
    batch = client.BatchV1Api()
    job_spec = build_assembly_job_spec(job)
    batch.create_namespaced_job(namespace=NAMESPACE, body=job_spec)
    return job_spec.metadata.name


async def dispatch_assembly_job(job) -> str:
    return await run_in_threadpool(_dispatch_assembly_job_sync, job)


async def watch_assembly_job_for_webhook(job):
    """Background task: polls the already-dispatched Job purely so the
    resume_url webhook can be fired once the Job reaches a terminal phase."""
    job_name = f"assemble-{job.job_id}"
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


def build_motion_convert_job_spec(job_id: str, still_path: str, output_path: str) -> "client.V1Job":
    job_name = f"job-{job_id}"
    container = client.V1Container(
        name="motion-convert",
        image="render-service:v3",
        command=["python3", "-c", (
            "import ffmpeg_assembly as fa, subprocess, sys; "
            "subprocess.run(fa.build_ken_burns_cmd(sys.argv[1], sys.argv[2]), check=True)"
        )],
        args=[still_path, output_path],
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


async def dispatch_motion_convert_job(job_id: str, still_path: str, output_path: str) -> str:
    def _sync():
        config.load_incluster_config()
        batch = client.BatchV1Api()
        spec = build_motion_convert_job_spec(job_id, still_path, output_path)
        batch.create_namespaced_job(namespace=NAMESPACE, body=spec)
        return spec.metadata.name
    return await run_in_threadpool(_sync)


async def watch_motion_convert_job(job_id: str, output_path: str):
    job_name = f"job-{job_id}"
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
