"""A Dataset Fabric profile.

A profile is the unit the Offline Evaluation page selects: a name, a purpose, and the
pipeline it grades. Its uploaded datasets live on `golden_datasets` rows that point back
here, so the evaluator stays unchanged and a run still reads one dataset.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_db.models.base import Base


class DatasetProfile(Base):
    __tablename__ = "dataset_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The pipeline this profile grades. NULL means "yet to be linked", which is a real
    # state: the datasets are authored before the pipeline exists.
    pipeline_slug: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # A snapshot of the pipeline's name, so the profile list does not need the ingestion
    # service to render.
    pipeline_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # The Knowledge Product whose document bucket holds the files. It lives in the
    # ingestion service's database, so this is a string and not a foreign key.
    knowledge_product_id: Mapped[str | None] = mapped_column(String, nullable=True)
    knowledge_product_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    datasets: Mapped[list["GoldenDataset"]] = relationship(  # noqa: F821
        back_populates="profile"
    )
