from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, DateTime, String
from datetime import datetime, timezone
import uuid


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


def generate_uuid():
    return str(uuid.uuid4())
