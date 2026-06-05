from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

DB_PATH = os.environ.get("CHAT_DB", "/root/used_v.sqlite3")

PACKAGE_TO_TIER = {
    "p1": 1,
    "p2": 2,
    "p3": 3,
}


@dataclass(frozen=True)
class PackagePlan:
    package_id: str
    tier_id: int
    name: str
    amount: float
    group_id: str


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _to_float(value, fallback: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return fallback


def normalize_package_id(package_id: str | None) -> str:
    raw = (package_id or "").strip().lower()
    return raw if raw in PACKAGE_TO_TIER else ""


def load_package_plans() -> dict[str, PackagePlan]:
    plans: dict[str, PackagePlan] = {}
    try:
        conn = _conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS package_page_config (key TEXT PRIMARY KEY, value TEXT)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS vip_tier_config (
                tier_id INTEGER PRIMARY KEY,
                tier_name TEXT,
                min_amount REAL,
                group_link TEXT
            )
            """
        )
        cur.execute("SELECT key, value FROM package_page_config")
        page_cfg = {str(row["key"]): "" if row["value"] is None else str(row["value"]) for row in cur.fetchall()}
        cur.execute("SELECT tier_id, min_amount, group_link FROM vip_tier_config")
        tier_cfg = {int(row["tier_id"]): row for row in cur.fetchall()}
        conn.close()
    except Exception:
        page_cfg = {}
        tier_cfg = {}

    defaults = {
        "p1": ("VIP Starter", 199.0),
        "p2": ("VIP Pro Pass", 499.0),
        "p3": ("VIP Lifetime", 999.0),
    }
    for package_id, tier_id in PACKAGE_TO_TIER.items():
        tier = tier_cfg.get(tier_id)
        default_name, default_amount = defaults[package_id]
        amount = _to_float(page_cfg.get(f"{package_id}_price"), 0.0)
        if amount <= 0 and tier is not None:
            amount = _to_float(tier["min_amount"], default_amount)
        if amount <= 0:
            amount = default_amount
        plans[package_id] = PackagePlan(
            package_id=package_id,
            tier_id=tier_id,
            name=str(page_cfg.get(f"{package_id}_name") or default_name),
            amount=amount,
            group_id=str(tier["group_link"] if tier is not None else "").strip(),
        )
    return plans


def get_package_plan(package_id: str | None) -> PackagePlan | None:
    normalized = normalize_package_id(package_id)
    if not normalized:
        return None
    return load_package_plans().get(normalized)
