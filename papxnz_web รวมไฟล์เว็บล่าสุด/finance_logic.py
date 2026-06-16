from __future__ import annotations

# เติมเงิน / ตรวจยอด / transaction / payment status
# ตอนนี้เป็น scaffold สำหรับให้ webapp.py, decision_api.py, webapp_setup.py เรียกใช้ร่วมกันก่อน

from pathlib import Path
from typing import Any

_CONTEXT: dict[str, Any] = {}


def configure_finance_logic(*, db_path: str | Path | None = None, source: str = "") -> dict[str, Any]:
    """Wire finance logic to the central app without implementing business rules yet."""
    if db_path is not None:
        _CONTEXT["db_path"] = str(db_path)
    if source:
        _CONTEXT["source"] = source
    return dict(_CONTEXT)


def get_finance_context() -> dict[str, Any]:
    return dict(_CONTEXT)
