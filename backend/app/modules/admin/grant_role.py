"""Give a platform role from the command line: the first superadmin, or a recovery (ADM-007).

``python -m app.modules.admin.grant_role --email EMAIL --role ROLE [--apply] [--reason TEXT]``

The account must already exist (registered in the app or on the website). Without ``--apply`` it
only reports what it would do. The grant is audited as a ``system`` action with the reason. The
role works from the account's next sign-in, which must use a second factor (TOTP), so set up the
authenticator in the staff console first. Later roles are given in the console (Staff page).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.principal import PlatformRole
from app.modules.identity import service as identity
from app.modules.observability import service as observability


async def grant(
    session: AsyncSession, *, email: str, role: str, reason: str, apply: bool, now: datetime
) -> str:
    """One line describing the outcome (never the email address itself)."""
    user_id = await identity.user_id_by_email(session, email)
    if user_id is None:
        return "No account uses that email address. Register it in the app or on the website first."
    view = await identity.account_admin_view(session, user_id)
    assert view is not None
    if role in view.roles:
        return f"Account {user_id} already has the {role} role."
    if not apply:
        return (
            f"Would give account {user_id} the {role} role (current roles: {view.roles or 'none'})."
        )
    await identity.assign_role(session, user_id, role, granted_by=None, now=now)
    observability.audit(
        session,
        actor_id=None,
        actor_type="system",
        action="staff_role.granted",
        resource_type="user",
        resource_id=user_id,
        metadata={"role": role, "reason": reason, "via": "grant_role command"},
    )
    return (
        f"Gave account {user_id} the {role} role. It works from the next sign-in with a "
        "second factor."
    )


async def _main(args: argparse.Namespace) -> int:
    from app.core.config import get_settings
    from app.core.db import Database

    database = Database.from_settings(get_settings(), pool_size=1, max_overflow=0)
    try:
        async with database.sessionmaker() as session, session.begin():
            line = await grant(
                session,
                email=args.email,
                role=args.role,
                reason=args.reason,
                apply=args.apply,
                now=datetime.now(UTC),
            )
    finally:
        await database.dispose()
    sys.stdout.write(line + "\n")
    if not args.apply:
        sys.stdout.write("Dry run: nothing changed. Add --apply to give the role.\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Give a Travel Buddy staff role")
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", required=True, choices=[r.value for r in PlatformRole])
    parser.add_argument("--reason", default="Initial staff setup")
    parser.add_argument("--apply", action="store_true")
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
