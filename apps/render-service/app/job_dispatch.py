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


def build_echo_job_spec(job_id: str) -> "client.V1Job":
    """Trivial busybox echo-and-exit Job spec, kept only until Task 9
    replaces /render's dispatch with a real ffmpeg Job spec."""
    job_name = f"echo-{job_id}"
    container = client.V1Container(
        name="echo",
        image="busybox:1.36",
        command=["sh", "-c", "echo done && sleep 2"],
    )
    pod_template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"job-id": job_id}),
        spec=client.V1PodSpec(containers=[container], restart_policy="Never"),
    )
    return client.V1Job(
        metadata=client.V1ObjectMeta(name=job_name),
        spec=client.V1JobSpec(
            template=pod_template,
            backoff_limit=2,
            ttl_seconds_after_finished=3600,
        ),
    )


def _dispatch_echo_job_sync(job_id: str) -> str:
    config.load_incluster_config()
    batch = client.BatchV1Api()
    job_spec = build_echo_job_spec(job_id)
    batch.create_namespaced_job(namespace=NAMESPACE, body=job_spec)
    return job_spec.metadata.name


async def dispatch_echo_job(job_id: str) -> str:
    return await run_in_threadpool(_dispatch_echo_job_sync, job_id)


async def watch_echo_job_for_webhook(job):
    """Background task: polls the already-dispatched Job purely so the
    resume_url webhook can be fired once the Job reaches a terminal phase."""
    job_name = f"echo-{job.job_id}"
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
