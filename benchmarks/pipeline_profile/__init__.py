"""Operational benchmarks for realistic plotsrv pipeline workflows.

These benchmarks deliberately live outside the runtime package.  They exercise
plotsrv as a user would: a pipeline process, optionally a separately hosted
server, watched files, and concurrent HTTP clients.
"""

from .models import PlotsrvConfigSpec, RunSpec, TableSpec, WorkloadSpec

__all__ = ["PlotsrvConfigSpec", "RunSpec", "TableSpec", "WorkloadSpec"]
