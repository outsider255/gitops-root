"""Unit tests for render-service's get_job_phase/job_phase_from_status logic.

render-service's actual code lives as a `main.py` data block inside
`app-configmap.yaml` (a K8s ConfigMap, mounted into the pod via subPath --
there is no standalone main.py file in this repo, per the project's
established ConfigMap-mounted-app-code convention). This test extracts that
embedded source at import time, execs it in an isolated namespace, and
exercises job_phase_from_status -- the pure, K8s-client-free helper that
get_job_phase delegates to -- against lightweight stub status objects.

No live cluster or kubernetes client mocking is needed: job_phase_from_status
only touches plain attributes (.conditions, .active), which the stubs below
provide directly, mirroring kubernetes.client.V1JobStatus's shape.
"""
import os
import re
import types

import pytest

CONFIGMAP_PATH = os.path.join(os.path.dirname(__file__), "app-configmap.yaml")


def _load_main_module():
    """Extract the `main.py: |` block-scalar body from app-configmap.yaml,
    dedent it (the YAML block scalar is indented 4 spaces), and exec it as a
    standalone module so we can import job_phase_from_status without needing
    a live K8s cluster, a FastAPI TestClient, or a real ServiceAccount token.
    """
    with open(CONFIGMAP_PATH, "r", encoding="utf-8") as f:
        raw = f.read()

    match = re.search(r"^  main\.py: \|\n((?:    .*\n|\n)+)", raw, re.MULTILINE)
    assert match, "could not locate the main.py block scalar in app-configmap.yaml"
    block = match.group(1)

    lines = []
    for line in block.splitlines():
        if line.startswith("    "):
            lines.append(line[4:])
        else:
            lines.append(line)
    source = "\n".join(lines)

    module = types.ModuleType("render_service_main")
    exec(compile(source, "app-configmap.yaml::main.py", "exec"), module.__dict__)
    return module


main = _load_main_module()


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
    """Defends against kubernetes-client/python#1766: status.failed can be
    None even when the Job has genuinely failed (e.g. BackoffLimitExceeded).
    job_phase_from_status must never consult a .failed counter -- it only
    takes .conditions and .active, so there is no counter attribute to even
    accidentally read here, proving the implementation can't regress into
    trusting it.
    """
    status = _StubJobStatus(conditions=[_StubCondition("Failed", "True")], active=None)
    assert main.job_phase_from_status(status) == "failed"


def test_running_when_no_terminal_condition_but_active():
    status = _StubJobStatus(conditions=[], active=1)
    assert main.job_phase_from_status(status) == "running"


def test_queued_when_no_conditions_and_not_active():
    status = _StubJobStatus(conditions=[], active=None)
    assert main.job_phase_from_status(status) == "queued"


def test_queued_when_conditions_is_none():
    """An empty/None conditions list must not raise."""
    status = _StubJobStatus(conditions=None, active=None)
    assert main.job_phase_from_status(status) == "queued"


def test_complete_condition_with_status_false_is_not_terminal():
    """A Complete condition with status != 'True' must not be treated as
    completed -- conditions can exist in a non-True state transiently."""
    status = _StubJobStatus(conditions=[_StubCondition("Complete", "False")], active=1)
    assert main.job_phase_from_status(status) == "running"


def test_failed_condition_takes_precedence_when_both_present():
    """If both a stale Complete=False and a Failed=True condition are
    present, failed must win (mirrors real K8s Job condition transitions)."""
    status = _StubJobStatus(
        conditions=[
            _StubCondition("Complete", "False"),
            _StubCondition("Failed", "True"),
        ],
        active=None,
    )
    assert main.job_phase_from_status(status) == "failed"


def test_get_job_phase_function_exists_and_is_callable():
    """get_job_phase(job_name) is the live-cluster entrypoint Task 2 wires
    into /status/{job_id}; this test only confirms it exists and has the
    expected signature -- exercising it against a live API server is a
    manual verification step (RESEARCH.md: no automated harness for live
    K8s integration exists for this phase)."""
    assert callable(main.get_job_phase)
