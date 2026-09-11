"""Small mechanical recovery policy; no model or user-approval inference."""
from __future__ import annotations
import subprocess
from mpres.util import TransientToolError

DEFAULTS = {'transient_tool_retries': 2, 'host_observation_retries': 2}
CONTENT_FAILURES = {'content', 'layout_or_renderer', 'pdf'}


def policy(settings: dict) -> dict:
    return {**DEFAULTS, **settings.get('recovery', {})}


def transient(exc: BaseException) -> bool:
    """Only typed failures from an actual external operation, including wrappers.

    Unknown ValueError/MPresError and missing installations are not retried.
    Playwright's general DOM contract timeout is NOT guessed to be transient.
    """
    seen=set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, (TransientToolError, subprocess.TimeoutExpired)):
            return True
        if type(exc).__name__ == 'TargetClosedError' and type(exc).__module__.startswith('playwright.'):
            return True
        exc=exc.__cause__
    return False
