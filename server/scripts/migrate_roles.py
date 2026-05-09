#!/usr/bin/env python3
"""
Phase-2 migration for AuthZ v2 role model.

What this migration does:
1) Normalizes user roles to:
   - superuser
   - stuff
   - general
2) Normalizes workspace membership roles to:
   - owner
   - admin
   - manager
   - agent
   - viewer
3) Normalizes workspace membership status to:
   - active
   - inactive
   - suspended
4) Backfills missing membership rows for non-superuser users with business_id.
5) Optionally applies DB constraints for role/status checks (PostgreSQL-safe, idempotent).

Usage:
  python server/scripts/migrate_roles.py --dry-run
  python server/scripts/migrate_roles.py --apply
  python server/scripts/migrate_roles.py --apply --apply-constraints
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

# Ensure `server/` is on sys.path so `app` package is importable.
SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_DIR = SCRIPT_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app.extensions import db
from app.models import Business, User, WorkspaceMembership

VALID_USER_ROLES = {"superuser", "stuff", "general"}
VALID_MEMBERSHIP_ROLES = {"owner", "admin", "manager", "agent", "viewer"}
VALID_MEMBERSHIP_STATUSES = {"active", "inactive", "suspended"}

# Legacy to v2 mapping for user.role.
USER_ROLE_MAP = {
    "owner": "stuff",
    "admin": "general",
    "manager": "general",
    "agent": "general",
    "viewer": "general",
}

# Legacy to v2 mapping for workspace_memberships.role.
MEMBERSHIP_ROLE_MAP = {
    "owner": "owner",
    "stuff": "admin",
    "general": "viewer",
}

# If membership is missing for a user with business_id, derive role from user role.
BACKFILL_ROLE_FROM_USER = {
    "stuff": "admin",
    "superuser": "admin",  # should rarely apply; guarded by business_id
    "general": "viewer",
    "owner": "admin",
    "admin": "admin",
    "manager": "manager",
    "agent": "agent",
    "viewer": "viewer",
}


@dataclass
class Plan:
    user_role_updates: list[tuple[int, str, str]]
    membership_role_updates: list[tuple[int, str, str]]
    membership_status_updates: list[tuple[int, str, str]]
    membership_backfills: list[tuple[int, int, str, str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase-2 AuthZ v2 role migration")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag, script runs as dry-run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes only (default behavior).",
    )
    parser.add_argument(
        "--apply-constraints",
        action="store_true",
        help="Also apply DB CHECK constraints for membership role/status.",
    )
    return parser.parse_args()


def normalize_user_role(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in VALID_USER_ROLES:
        return value
    if value in USER_ROLE_MAP:
        return USER_ROLE_MAP[value]
    return "general"


def normalize_membership_role(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in VALID_MEMBERSHIP_ROLES:
        return value
    if value in MEMBERSHIP_ROLE_MAP:
        return MEMBERSHIP_ROLE_MAP[value]
    return "viewer"


def normalize_membership_status(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in VALID_MEMBERSHIP_STATUSES:
        return value
    return "active"


def build_plan() -> Plan:
    user_role_updates: list[tuple[int, str, str]] = []
    membership_role_updates: list[tuple[int, str, str]] = []
    membership_status_updates: list[tuple[int, str, str]] = []
    membership_backfills: list[tuple[int, int, str, str]] = []

    users = User.query.all()
    memberships = WorkspaceMembership.query.all()

    membership_index: set[tuple[int, int]] = {
        (m.business_id, m.user_id) for m in memberships
    }

    for user in users:
        target = normalize_user_role(user.role)
        if target != user.role:
            user_role_updates.append((user.id, user.role, target))

    for m in memberships:
        next_role = normalize_membership_role(m.role)
        if next_role != m.role:
            membership_role_updates.append((m.id, m.role, next_role))

        next_status = normalize_membership_status(m.status)
        if next_status != m.status:
            membership_status_updates.append((m.id, m.status, next_status))

    # Backfill owner/stuff membership from businesses.owner_user_id.
    businesses = Business.query.all()
    for business in businesses:
        if not business.owner_user_id:
            continue
        key = (business.id, business.owner_user_id)
        if key in membership_index:
            continue
        membership_backfills.append((business.id, business.owner_user_id, "owner", "active"))

    return Plan(
        user_role_updates=user_role_updates,
        membership_role_updates=membership_role_updates,
        membership_status_updates=membership_status_updates,
        membership_backfills=membership_backfills,
    )


def apply_plan(plan: Plan) -> None:
    if plan.user_role_updates:
        user_target = {row_id: new for row_id, _, new in plan.user_role_updates}
        for user in User.query.all():
            if user.id in user_target:
                user.role = user_target[user.id]

    if plan.membership_role_updates or plan.membership_status_updates:
        role_target = {row_id: new for row_id, _, new in plan.membership_role_updates}
        status_target = {row_id: new for row_id, _, new in plan.membership_status_updates}
        for m in WorkspaceMembership.query.all():
            if m.id in role_target:
                m.role = role_target[m.id]
            if m.id in status_target:
                m.status = status_target[m.id]

    for business_id, user_id, role, status in plan.membership_backfills:
        exists = WorkspaceMembership.query.filter_by(
            business_id=business_id, user_id=user_id
        ).first()
        if exists is None:
            db.session.add(
                WorkspaceMembership(
                    business_id=business_id,
                    user_id=user_id,
                    role=role,
                    status=status,
                )
            )

    db.session.commit()


def apply_constraints_if_requested() -> None:
    # PostgreSQL-safe idempotent constraints.
    statements = [
        """
        ALTER TABLE workspace_memberships
        ADD CONSTRAINT ck_workspace_memberships_role_v2
        CHECK (role IN ('owner','admin','manager','agent','viewer'))
        """,
        """
        ALTER TABLE workspace_memberships
        ADD CONSTRAINT ck_workspace_memberships_status_v2
        CHECK (status IN ('active','inactive','suspended'))
        """,
    ]
    for sql in statements:
        try:
            db.session.execute(text(sql))
            db.session.commit()
        except Exception as exc:  # noqa: BLE001
            # Ignore duplicate-constraint failures to keep operation idempotent.
            db.session.rollback()
            message = str(exc).lower()
            if "already exists" in message or "duplicate" in message:
                continue
            raise


def print_plan(plan: Plan) -> None:
    print("Phase-2 migration plan summary:")
    print(f"  user role updates: {len(plan.user_role_updates)}")
    print(f"  membership role updates: {len(plan.membership_role_updates)}")
    print(f"  membership status updates: {len(plan.membership_status_updates)}")
    print(f"  membership backfills: {len(plan.membership_backfills)}")

    if plan.user_role_updates[:10]:
        print("\nSample user role updates (up to 10):")
        for row_id, old, new in plan.user_role_updates[:10]:
            print(f"  user_id={row_id}: {old} -> {new}")

    if plan.membership_role_updates[:10]:
        print("\nSample membership role updates (up to 10):")
        for row_id, old, new in plan.membership_role_updates[:10]:
            print(f"  membership_id={row_id}: {old} -> {new}")

    if plan.membership_status_updates[:10]:
        print("\nSample membership status updates (up to 10):")
        for row_id, old, new in plan.membership_status_updates[:10]:
            print(f"  membership_id={row_id}: {old} -> {new}")

    if plan.membership_backfills[:10]:
        print("\nSample membership backfills (up to 10):")
        for business_id, user_id, role, status in plan.membership_backfills[:10]:
            print(
                f"  business_id={business_id}, user_id={user_id}, role={role}, status={status}"
            )


def main() -> int:
    args = parse_args()
    dry_run = (not args.apply) or args.dry_run

    from app import create_app

    app = create_app()
    with app.app_context():
        plan = build_plan()
        print_plan(plan)

        if dry_run:
            print("\nDry-run mode: no changes written.")
            return 0

        apply_plan(plan)
        if args.apply_constraints:
            apply_constraints_if_requested()
        print("\nApply mode: migration applied successfully.")
        if args.apply_constraints:
            print("Constraints apply step completed (idempotent).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
