#!/usr/bin/env python3
"""
Migrate legacy role values to workspace-role model.

Legacy:
- users.role: stuff, general
- workspace_memberships.role: stuff, general

Target:
- users.role/workspace_memberships.role: owner, admin, manager, agent, viewer

Defaults:
- stuff   -> owner
- general -> viewer

Usage examples:
- Dry run (recommended first):
  python server/scripts/migrate_roles.py --dry-run

- Apply with default mapping:
  python server/scripts/migrate_roles.py --apply

- Apply with general->agent mapping:
  python server/scripts/migrate_roles.py --apply --general-target agent
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure `server/` is on sys.path so `app` package is importable.
SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_DIR = SCRIPT_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app import create_app
from app.extensions import db
from app.models import User, WorkspaceMembership

VALID_GENERAL_TARGETS = {"viewer", "agent"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate legacy roles to workspace roles")
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
        "--general-target",
        default="viewer",
        choices=sorted(VALID_GENERAL_TARGETS),
        help="Target role for legacy 'general' values.",
    )
    return parser.parse_args()


def migration_plan(general_target: str) -> dict[str, str]:
    return {
        "stuff": "owner",
        "general": general_target,
    }


def collect_changes(role_map: dict[str, str]) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str]]]:
    user_changes: list[tuple[int, str, str]] = []
    membership_changes: list[tuple[int, str, str]] = []

    users = User.query.all()
    for user in users:
        if user.role in role_map:
            user_changes.append((user.id, user.role, role_map[user.role]))

    memberships = WorkspaceMembership.query.all()
    for member in memberships:
        if member.role in role_map:
            membership_changes.append((member.id, member.role, role_map[member.role]))

    return user_changes, membership_changes


def apply_changes(role_map: dict[str, str]) -> tuple[int, int]:
    user_count = 0
    membership_count = 0

    for user in User.query.all():
        if user.role in role_map:
            user.role = role_map[user.role]
            user_count += 1

    for member in WorkspaceMembership.query.all():
        if member.role in role_map:
            member.role = role_map[member.role]
            membership_count += 1

    db.session.commit()
    return user_count, membership_count


def main() -> int:
    args = parse_args()
    dry_run = (not args.apply) or args.dry_run

    role_map = migration_plan(args.general_target)

    app = create_app()
    with app.app_context():
        user_changes, membership_changes = collect_changes(role_map)

        print("Role migration plan:")
        for src, dst in role_map.items():
            print(f"  - {src} -> {dst}")

        print("\nDetected changes:")
        print(f"  users: {len(user_changes)}")
        print(f"  memberships: {len(membership_changes)}")

        if dry_run:
            print("\nDry-run mode: no changes written.")
            if user_changes[:10]:
                print("\nSample user changes (up to 10):")
                for row_id, old, new in user_changes[:10]:
                    print(f"  user_id={row_id}: {old} -> {new}")
            if membership_changes[:10]:
                print("\nSample membership changes (up to 10):")
                for row_id, old, new in membership_changes[:10]:
                    print(f"  membership_id={row_id}: {old} -> {new}")
            return 0

        user_count, membership_count = apply_changes(role_map)
        print("\nApplied successfully:")
        print(f"  users updated: {user_count}")
        print(f"  memberships updated: {membership_count}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
