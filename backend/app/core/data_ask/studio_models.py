"""一句话分析工作台的分析模板表（由 init_db 的 create_all 自动创建）。"""
from sqlalchemy import JSON, Boolean, Column, Integer, String

from app.db.base import Base, TimestampMixin, generate_uuid


class AnalysisTemplate(Base, TimestampMixin):
    """业务侧可编辑的分析模板：一句话命中关键词后，按 sections 依次出表/出图。"""

    __tablename__ = "analysis_templates"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    data_source_id = Column(String(64), nullable=False, index=True)
    name = Column(String(120), nullable=False, default="")
    # 命中词：任一命中即可匹配（多个命中按命中数排序）
    keywords = Column(JSON, default=list)
    # [{"title": "...", "question": "...", "chart": "auto|bar|line|pie|table"}]
    sections = Column(JSON, default=list)
    enabled = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_by = Column(String(64), nullable=True)
