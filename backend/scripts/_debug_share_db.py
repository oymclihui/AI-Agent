import asyncio
import traceback
import uuid

from sqlalchemy import select

from app.db.base import generate_uuid
from app.db.models import Agent, AgentShare, AgentShareGranteeType, AgentSharePermission, AgentVisibility, User
from app.db.session import AsyncSessionLocal
from app.schemas.agent import AgentSharingUpdate, AgentShareGrantIn, AgentShareGranteeType as GType, AgentSharePermission as PType, AgentVisibility as VType


async def main():
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User).limit(2))).scalars().all()
        if len(users) < 2:
            print("need 2 users")
            return
        owner, other = users[0], users[1]
        agent = Agent(
            id=generate_uuid(),
            owner_id=owner.id,
            name=f"dbg-{uuid.uuid4().hex[:6]}",
            role="R",
            goal="G",
            visibility=AgentVisibility.private.value,
        )
        db.add(agent)
        await db.flush()
        payload = AgentSharingUpdate(
            visibility=VType.shared,
            grants=[AgentShareGrantIn(grantee_type=GType.user, grantee_id=other.id, permission=PType.use)],
        )
        try:
            agent.visibility = payload.visibility.value
            for grant in payload.grants:
                db.add(AgentShare(
                    id=generate_uuid(),
                    agent_id=agent.id,
                    grantee_type=AgentShareGranteeType(grant.grantee_type),
                    grantee_id=grant.grantee_id,
                    permission=AgentSharePermission(grant.permission),
                    granted_by=owner.id,
                ))
            await db.flush()
            print("OK", agent.visibility)
        except Exception:
            traceback.print_exc()

asyncio.run(main())
