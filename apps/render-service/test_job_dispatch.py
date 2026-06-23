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
