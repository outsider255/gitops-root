import os
import urllib.request
from fastapi import FastAPI, HTTPException, BackgroundTasks, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

import job_dispatch

app = FastAPI()

OUTBOX_BASE = "/outbox/"
ASSETS_BASE = "/assets/"


class OverlayConfig(BaseModel):
    qr_url: Optional[str] = None
    affirmation_text: Optional[str] = None
    watermark: Optional[str] = None


class JobSpec(BaseModel):
    job_id: str
    video_id: str
    category: str
    track_ids: list[str]
    loop_ids: list[str]
    overlay_config: OverlayConfig = OverlayConfig()
    output_path: str
    resume_url: Optional[str] = None


class MotionConvertRequest(BaseModel):
    loop_id: str
    still_path: str
    category: str


class DownloadToAssetsRequest(BaseModel):
    source_url: str
    target_path: str


class ClipRequest(BaseModel):
    job_id: str
    main_loop_path: str
    main_track_path: str
    audio_start_s: float = 30.0
    audio_duration_s: float = 40.0
    output_path: str


class UploadYouTubeRequest(BaseModel):
    job_id: str
    file_path: str
    title: str
    description: str
    privacy_status: str = "private"
    category_id: str = "22"


class UploadOneDriveRequest(BaseModel):
    job_id: str
    file_path: str
    target_path: str


@app.post("/render", status_code=202)
async def render(job: JobSpec, background_tasks: BackgroundTasks):
    real_base = os.path.realpath(OUTBOX_BASE)
    real_target = os.path.realpath(job.output_path)
    if not (real_target == real_base or real_target.startswith(real_base + os.sep)):
        raise HTTPException(status_code=400, detail=f"output_path must be under {OUTBOX_BASE}")

    os.makedirs(os.path.dirname(real_target), exist_ok=True)

    job_dispatch.JOBS[job.job_id] = {
        "status": "accepted",
        "output_path": None,
        "requested_output_path": job.output_path,
    }
    try:
        job_name = await job_dispatch.dispatch_assembly_job(job)
        job_dispatch.JOBS[job.job_id]["job_name"] = job_name
    except job_dispatch.ApiException as e:
        job_dispatch.JOBS[job.job_id]["status"] = "failed"
        job_dispatch.JOBS[job.job_id]["error"] = str(e)
        raise HTTPException(status_code=502, detail=str(e))

    job_dispatch.JOBS[job.job_id]["status"] = "queued"
    background_tasks.add_task(job_dispatch.watch_assembly_job_for_webhook, job)
    return {"job_id": job.job_id, "status": "accepted"}


@app.post("/render/clip", status_code=202)
async def render_clip(req: ClipRequest, background_tasks: BackgroundTasks):
    real_base = os.path.realpath(OUTBOX_BASE)
    real_target = os.path.realpath(req.output_path)
    if not (real_target == real_base or real_target.startswith(real_base + os.sep)):
        raise HTTPException(status_code=400, detail=f"output_path must be under {OUTBOX_BASE}")

    os.makedirs(os.path.dirname(real_target), exist_ok=True)

    job_dispatch.JOBS[req.job_id] = {
        "status": "accepted",
        "output_path": None,
        "requested_output_path": req.output_path,
    }
    job_name = await job_dispatch.dispatch_clip_job(req)
    job_dispatch.JOBS[req.job_id]["job_name"] = job_name
    job_dispatch.JOBS[req.job_id]["status"] = "queued"
    background_tasks.add_task(job_dispatch.watch_clip_job, req)
    return {"job_id": req.job_id, "job_name": job_name}


def _bearer_token(authorization: Optional[str]) -> str:
    """The upload-dispatch HTTP nodes in n8n use predefinedCredentialType
    (the same existing YouTube/OneDrive OAuth2 credential used everywhere
    else in this pipeline) so n8n attaches a valid, auto-refreshed Bearer
    token to the request itself -- the token only ever exists as this
    header (n8n doesn't persist credential-attached headers in its
    execution log the way it would a JSON body field), never as data we
    echo back or store."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization[len("Bearer "):]


@app.post("/upload/youtube", status_code=202)
async def upload_youtube(req: UploadYouTubeRequest, background_tasks: BackgroundTasks, authorization: str = Header(None)):
    access_token = _bearer_token(authorization)
    real_base = os.path.realpath(OUTBOX_BASE)
    real_target = os.path.realpath(req.file_path)
    if not real_target.startswith(real_base + os.sep):
        raise HTTPException(status_code=400, detail=f"file_path must be under {OUTBOX_BASE}")
    if not os.path.exists(real_target):
        raise HTTPException(status_code=404, detail="file not found on disk")

    job_dispatch.JOBS[req.job_id] = {"status": "queued"}
    background_tasks.add_task(job_dispatch.upload_youtube, req, access_token)
    return {"job_id": req.job_id, "status": "accepted"}


@app.post("/upload/onedrive", status_code=202)
async def upload_onedrive(req: UploadOneDriveRequest, background_tasks: BackgroundTasks, authorization: str = Header(None)):
    access_token = _bearer_token(authorization)
    real_base = os.path.realpath(OUTBOX_BASE)
    real_target = os.path.realpath(req.file_path)
    if not real_target.startswith(real_base + os.sep):
        raise HTTPException(status_code=400, detail=f"file_path must be under {OUTBOX_BASE}")
    if not os.path.exists(real_target):
        raise HTTPException(status_code=404, detail="file not found on disk")

    job_dispatch.JOBS[req.job_id] = {"status": "queued"}
    background_tasks.add_task(job_dispatch.upload_onedrive, req, access_token)
    return {"job_id": req.job_id, "status": "accepted"}


@app.post("/process/motion-convert", status_code=202)
async def process_motion_convert(req: MotionConvertRequest, background_tasks: BackgroundTasks):
    job_id = f"motionconvert-{req.loop_id}"
    output_path = f"/assets/loops/{req.loop_id}.mp4"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    job_dispatch.JOBS[job_id] = {
        "status": "accepted",
        "output_path": None,
        "requested_output_path": output_path,
    }
    job_name = await job_dispatch.dispatch_motion_convert_job(job_id, req.still_path, output_path)
    job_dispatch.JOBS[job_id]["job_name"] = job_name
    job_dispatch.JOBS[job_id]["status"] = "queued"
    background_tasks.add_task(job_dispatch.watch_motion_convert_job, job_id, output_path)
    return {"job_id": job_id, "job_name": job_name}


@app.post("/process/download-to-assets")
def download_to_assets(req: DownloadToAssetsRequest):
    real_base = os.path.realpath(ASSETS_BASE)
    real_target = os.path.realpath(req.target_path)
    if not (real_target == real_base or real_target.startswith(real_base + os.sep)):
        raise HTTPException(status_code=400, detail=f"target_path must be under {ASSETS_BASE}")

    os.makedirs(os.path.dirname(real_target), exist_ok=True)
    request = urllib.request.Request(req.source_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request) as response, open(real_target, "wb") as f:
        f.write(response.read())
    return {"target_path": req.target_path, "downloaded": True}


@app.get("/status/{job_id}")
async def status(job_id: str):
    if job_id not in job_dispatch.JOBS:
        raise HTTPException(status_code=404, detail="unknown job_id")

    if "job_name" not in job_dispatch.JOBS[job_id]:
        return {"job_id": job_id, **job_dispatch.JOBS[job_id]}

    job_name = job_dispatch.JOBS[job_id]["job_name"]
    try:
        from fastapi.concurrency import run_in_threadpool
        phase = await run_in_threadpool(job_dispatch.get_job_phase, job_name)
    except job_dispatch.ApiException as e:
        raise HTTPException(status_code=502, detail=str(e))

    job_dispatch.JOBS[job_id]["status"] = phase
    if phase == "completed" and not job_dispatch.JOBS[job_id].get("output_path"):
        job_dispatch.JOBS[job_id]["output_path"] = job_dispatch.JOBS[job_id]["requested_output_path"]
    return {"job_id": job_id, **job_dispatch.JOBS[job_id]}


@app.get("/outbox/{job_id}/download")
def download_output(job_id: str):
    if job_id not in job_dispatch.JOBS:
        raise HTTPException(status_code=404, detail="unknown job_id")
    output_path = job_dispatch.JOBS[job_id].get("output_path")
    if not output_path:
        raise HTTPException(status_code=400, detail="job has no output_path (not completed yet)")

    real_base = os.path.realpath(OUTBOX_BASE)
    real_target = os.path.realpath(output_path)
    if not (real_target == real_base or real_target.startswith(real_base + os.sep)):
        raise HTTPException(status_code=400, detail=f"output_path must be under {OUTBOX_BASE}")

    if not os.path.exists(real_target):
        raise HTTPException(status_code=404, detail="output file not found on disk")

    return FileResponse(real_target, media_type="video/mp4", filename=os.path.basename(real_target))


@app.delete("/outbox/{job_id}")
def delete_output(job_id: str):
    if job_id not in job_dispatch.JOBS:
        raise HTTPException(status_code=404, detail="unknown job_id")
    output_path = job_dispatch.JOBS[job_id].get("output_path")
    if not output_path:
        raise HTTPException(status_code=400, detail="job has no output_path (not completed yet)")

    real_base = os.path.realpath(OUTBOX_BASE)
    real_target = os.path.realpath(output_path)
    if not (real_target == real_base or real_target.startswith(real_base + os.sep)):
        raise HTTPException(status_code=400, detail=f"output_path must be under {OUTBOX_BASE}")

    if not os.path.exists(real_target):
        raise HTTPException(status_code=404, detail="output file not found on disk")

    os.remove(real_target)
    job_dispatch.JOBS[job_id]["deleted"] = True
    return {"job_id": job_id, "deleted": True}


@app.get("/healthz")
def healthz():
    return {"ok": True}
