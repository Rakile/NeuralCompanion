"""Owned adapters for legacy workers that cannot depend on runtime services."""

from __future__ import annotations

from core.runtime.identifiers import RunId, WorkLease
from core.runtime.lifecycle import WorkerSupervisor


def create_supervisor(*, join_timeout_seconds: float = 4.0):
    return WorkerSupervisor(join_timeout_seconds=join_timeout_seconds)


def detached_lease():
    return WorkLease(RunId(0))


__all__ = ["create_supervisor", "detached_lease"]
