"""Unit tests for render-service's get_job_phase/job_phase_from_status logic.

Now a normal import-based test -- the YAML-block-scalar extraction
trick (the previous test_job_status.py) is no longer needed because
job_dispatch.py is a real file in the built image, not a ConfigMap entry.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

import job_dispatch as main


class _StubCondition:
    def __init__(self, type_, status):
        self.type = type_
        self.status = status


class _StubJobStatus:
    def __init__(self, conditions=None, active=None):
        self.conditions = conditions
        self.active = active


def test_completed_when_complete_condition_true():
    status = _StubJobStatus(conditions=[_StubCondition("Complete", "True")])
    assert main.job_phase_from_status(status) == "completed"


def test_failed_when_failed_condition_true_even_if_failed_counter_none():
    status = _StubJobStatus(conditions=[_StubCondition("Failed", "True")], active=None)
    assert main.job_phase_from_status(status) == "failed"


def test_running_when_no_terminal_condition_but_active():
    status = _StubJobStatus(conditions=[], active=1)
    assert main.job_phase_from_status(status) == "running"


def test_queued_when_no_conditions_and_not_active():
    status = _StubJobStatus(conditions=[], active=None)
    assert main.job_phase_from_status(status) == "queued"


def test_queued_when_conditions_is_none():
    status = _StubJobStatus(conditions=None, active=None)
    assert main.job_phase_from_status(status) == "queued"


def test_complete_condition_with_status_false_is_not_terminal():
    status = _StubJobStatus(conditions=[_StubCondition("Complete", "False")], active=1)
    assert main.job_phase_from_status(status) == "running"


def test_failed_condition_takes_precedence_when_both_present():
    status = _StubJobStatus(
        conditions=[
            _StubCondition("Complete", "False"),
            _StubCondition("Failed", "True"),
        ],
        active=None,
    )
    assert main.job_phase_from_status(status) == "failed"


def test_get_job_phase_function_exists_and_is_callable():
    assert callable(main.get_job_phase)


def _stub_resolve_asset_path(kind, asset_id):
    ext = "mp4" if kind == "loops" else "mp3"
    return f"/assets/{kind}/{asset_id}.{ext}"


def test_build_assembly_job_spec_uses_render_service_image(monkeypatch):
    monkeypatch.setattr(main, "resolve_asset_path", _stub_resolve_asset_path)

    class _FakeJob:
        job_id = "20260623120000"
        loop_ids = ["loop_dummy_001"]
        track_ids = ["trk_dummy_001"]
        output_path = "/outbox/test.mp4"
        category = "deep_focus"

    spec = main.build_assembly_job_spec(_FakeJob())
    assert spec.spec.template.spec.containers[0].image == "render-service:v10"


def test_build_assembly_job_spec_mounts_outbox_and_assets(monkeypatch):
    monkeypatch.setattr(main, "resolve_asset_path", _stub_resolve_asset_path)

    class _FakeJob:
        job_id = "20260623120000"
        loop_ids = ["loop_dummy_001"]
        track_ids = ["trk_dummy_001"]
        output_path = "/outbox/test.mp4"
        category = "deep_focus"

    spec = main.build_assembly_job_spec(_FakeJob())
    mount_paths = {m.mount_path for m in spec.spec.template.spec.containers[0].volume_mounts}
    assert mount_paths == {"/outbox", "/assets"}


def test_build_assembly_job_spec_passes_loop_and_track_paths_as_args(monkeypatch):
    monkeypatch.setattr(main, "resolve_asset_path", _stub_resolve_asset_path)

    class _FakeJob:
        job_id = "20260623120000"
        loop_ids = ["loop_dummy_001"]
        track_ids = ["trk_dummy_001"]
        output_path = "/outbox/test.mp4"
        category = "deep_focus"

    spec = main.build_assembly_job_spec(_FakeJob())
    args = spec.spec.template.spec.containers[0].args
    assert "/assets/loops/loop_dummy_001.mp4" in args
    assert "/assets/tracks/trk_dummy_001.mp3" in args
    assert "/outbox/test.mp4" in args


def test_build_assembly_job_spec_resolves_paths_via_asset_library_not_naming_convention(monkeypatch):
    """Assets aren't reliably named after their db id (e.g. Mode A-generated
    loop files keep their motion-convert job id, not the db id asset-library
    assigns), so build_assembly_job_spec must look paths up, not guess them."""
    calls = []

    def _fake_resolve(kind, asset_id):
        calls.append((kind, asset_id))
        return f"/assets/{kind}/totally-different-filename.bin"

    monkeypatch.setattr(main, "resolve_asset_path", _fake_resolve)

    class _FakeJob:
        job_id = "20260623120000"
        loop_ids = ["loop_4b50874c8f"]
        track_ids = ["trk_9d180f3602"]
        output_path = "/outbox/test.mp4"
        category = "deep_focus"

    spec = main.build_assembly_job_spec(_FakeJob())
    args = spec.spec.template.spec.containers[0].args
    assert "/assets/loops/totally-different-filename.bin" in args
    assert "/assets/tracks/totally-different-filename.bin" in args
    assert ("loops", "loop_4b50874c8f") in calls
    assert ("tracks", "trk_9d180f3602") in calls


def test_k8s_job_name_strips_underscores_for_k8s_resource_name_validity():
    assert main.k8s_job_name("job", "motionconvert-loop_dummy_001") == "job-motionconvert-loop-dummy-001"
    assert main.k8s_job_name("assemble", "20260623_120000") == "assemble-20260623-120000"


def test_build_motion_convert_job_spec_job_name_has_no_underscores():
    spec = main.build_motion_convert_job_spec(
        job_id="motionconvert-loop_dummy_001",
        still_path="/assets/stills/still_001.png",
        output_path="/assets/loops/loop_dummy_001.mp4"
    )
    assert "_" not in spec.metadata.name


def test_build_motion_convert_job_spec_uses_render_service_image():
    spec = main.build_motion_convert_job_spec(
        job_id="motionconvert-loop_dummy_001",
        still_path="/assets/stills/still_001.png",
        output_path="/assets/loops/loop_dummy_001.mp4"
    )
    assert spec.spec.template.spec.containers[0].image == "render-service:v10"


def test_build_motion_convert_job_spec_mounts_assets():
    spec = main.build_motion_convert_job_spec(
        job_id="motionconvert-loop_dummy_001",
        still_path="/assets/stills/still_001.png",
        output_path="/assets/loops/loop_dummy_001.mp4"
    )
    mount_paths = {m.mount_path for m in spec.spec.template.spec.containers[0].volume_mounts}
    assert mount_paths == {"/assets"}


def test_build_motion_convert_job_spec_passes_still_and_output_paths_as_args():
    spec = main.build_motion_convert_job_spec(
        job_id="motionconvert-loop_dummy_001",
        still_path="/assets/stills/still_001.png",
        output_path="/assets/loops/loop_dummy_001.mp4"
    )
    args = spec.spec.template.spec.containers[0].args
    assert args == ["/assets/stills/still_001.png", "/assets/loops/loop_dummy_001.mp4"]


def test_build_motion_convert_job_spec_has_correct_container_name_and_command():
    spec = main.build_motion_convert_job_spec(
        job_id="motionconvert-loop_dummy_001",
        still_path="/assets/stills/still_001.png",
        output_path="/assets/loops/loop_dummy_001.mp4"
    )
    assert spec.spec.template.spec.containers[0].name == "motion-convert"
    command = spec.spec.template.spec.containers[0].command
    assert len(command) == 3
    assert command[0] == "python3"
    assert command[1] == "-c"
    assert "ffmpeg_assembly" in command[2]
    assert "build_ken_burns_cmd" in command[2]
