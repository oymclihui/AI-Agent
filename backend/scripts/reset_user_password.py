"""Reset a user's password from the command line (emergency / ops use).

Usage:
  cd backend
  python scripts/reset_user_password.py --login admin --password NewPass123
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import or_, select

from app.core.auth.security import hash_password
from app.db.models import User
from app.db.session import AsyncSessionLocal


async def main(login: str, password: str) -> None:
    login_id = login.strip()
    email_id = login_id.lower()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                or_(User.employee_no == login_id, User.email == email_id)
            ).limit(1)
        )
        user = result.scalar_one_or_none()
        if not user:
            print(f"User not found: {login_id}", file=sys.stderr)
            sys.exit(1)
        user.password_hash = hash_password(password)
        await db.commit()
        label = user.employee_no or user.email or user.id
        print(f"Password updated for user: {label}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset AI-AGENT user password")
    parser.add_argument("--login", required=True, help="Employee number or email")
    parser.add_argument("--password", required=True, help="New password (min 6 chars)")
    args = parser.parse_args()
    if len(args.password) < 6:
        print("Password must be at least 6 characters", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(args.login, args.password))
