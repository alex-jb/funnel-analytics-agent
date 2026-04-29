"""Brief composer — re-exported from solo-founder-os.

Backward-compat shim. New code should:

    from solo_founder_os.brief import compose_brief, has_critical
"""
from __future__ import annotations
from solo_founder_os.brief import (
    compose_brief,
    has_critical,
    SEVERITY_ICON,
)

__all__ = ["compose_brief", "has_critical", "SEVERITY_ICON"]
