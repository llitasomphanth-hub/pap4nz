from __future__ import annotations

# login / signup / session / account link
# ตอนนี้เป็น scaffold สำหรับให้ webapp.py, decision_api.py, webapp_setup.py เรียกใช้ร่วมกันก่อน

from pathlib import Path
from typing import Any

_CONTEXT: dict[str, Any] = {}


def configure_auth_logic(*, db_path: str | Path | None = None, source: str = "") -> dict[str, Any]:
    """Wire auth/session/account-link logic without implementing auth rules yet."""
    if db_path is not None:
        _CONTEXT["db_path"] = str(db_path)
    if source:
        _CONTEXT["source"] = source
    return dict(_CONTEXT)


def get_auth_context() -> dict[str, Any]:
    return dict(_CONTEXT)
