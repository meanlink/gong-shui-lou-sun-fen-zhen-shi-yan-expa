from sqlalchemy import String, JSON, Double, Integer, ForeignKey, Boolean, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class TransferBatch(Base):
    """夜巡大批样本的分段接入会话：先登记总段数、总行数与整批指纹，乱序收段后一次性发布为 Dataset。"""
    __tablename__ = 'transfer_batches'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='night-patrol.upload')
    total_segments: Mapped[int] = mapped_column(Integer)
    total_rows: Mapped[int] = mapped_column(Integer)
    batch_checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default='collecting')
    # collecting 收段中 / ready 齐备待发布 / publishing 发布进行中 / published 已发布 /
    # revoking 撤销进行中 / revoked 已撤销 / failed 校验失败（保留已收内容并定位原因）
    issue: Mapped[dict] = mapped_column(JSON, default=dict)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)
    published_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    revoked_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class TransferSegment(Base):
    __tablename__ = 'transfer_segments'
    __table_args__ = (
        UniqueConstraint('batch_id', 'segment_index', name='uq_transfer_segment_index'),
        Index('ix_transfer_segment_batch', 'batch_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey('transfer_batches.id'))
    segment_index: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    records: Mapped[list] = mapped_column(JSON)
    received_at: Mapped[float] = mapped_column(Double)
