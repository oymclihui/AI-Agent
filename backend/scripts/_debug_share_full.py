import asyncio
import traceback
import uuid

from sqlalchemy import select

from app.db.base import generate_uuid
from app.db.models import Agent, AgentShare, AgentShareGranteeType, AgentSharePermission, AgentVisibility, User
from app.db.session import AsyncSessionLocal
from app.schemas.agent import AgentSharingUpdate, AgentShareGrantIn, AgentShareGranteeType as GT, AgentSharePermission as GP, AgentVisibility as V
from app.core.auth.agent_access import write_agent_share_audit


async def main():
    async with AsyncSessionLocal() as db:
        owner = (await db.execute(select(User).order_by(User.created_at.desc()).limit(1))).scalar_one()
        other = (await db.execute(select(User).order_by(User.created_at.desc()).offset(1).limit(1))).scalar_one()
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
            visibility=V.shared,
            grants=[AgentShareGrantIn(grantee_type=GT.user, grantee_id=other.id, permission=GP.use)],
        )
        agent_id = agent.id
        try:
            before = {"visibility": (agent.visibility or "private")}
            agent.visibility = payload.visibility.value
            existing = await db.execute(select(AgentShare).where(AgentShare.agent_id == agent_id))
            for row in existing.scalars().all():
                await db.delete(row)
            if payload.visibility == V.shared:
                for grant in payload.grants:
                    db.add(AgentShare(
                        id=generate_uuid(),
                        agent_id=agent_id,
                        grantee_type=AgentShareGranteeType(
                            grant.grantee_type.value if hasattr(grant.grantee_type, "value") else grant.grantee_type
                        ),
                        grantee_id=grant.grantee_id,
                        permission=AgentSharePermission(
                            grant.permission.value if hasattr(grant.permission, "value") else grant.permission
                        ),
                        granted_by=owner.id,
                    ))
            await write_agent_share_audit(
                db,
                actor_id=owner.id,
                agent_id=agent_id,
                action="sharing_update",
                details={"before": before, "after": payload.model_dump(mode="json")},
            )
            await db.flush()
            await db.commit()
            print("OK")
        except Exception:
            traceback.print_exc()

asyncio.run(main())
