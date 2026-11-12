"""Synthetic dataset profiles and their versions.

A profile binds one Knowledge Product to the Qdrant collection its chunks live in. A
version is one generation run: the settings it used, how far it has got, and the rows it
produced. The rows are ordinary `golden_datasets` rows that point back at the version, so
Offline Evaluation needs no change to select them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_db.models.base import Base


class SyntheticDatasetProfile(Base):
    """One profile per dataset author and Knowledge Product.

    The table carries the Synthetic name from its first use. `source` separates the two
    authors: `synthetic` profiles are generated, `manual` profiles hold uploads. A name is
    unique inside one source, and the active profile is one per product per source.
    """

    __tablename__ = "synthetic_dataset_profiles"
    __table_args__ = (
        UniqueConstraint("name", "source", name="uq_synthetic_profile_name_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # "synthetic" or "manual": the page that created the profile.
    source: Mapped[str] = mapped_column(String, nullable=False, server_default="synthetic")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The Knowledge Product lives in the ingestion service's database, so this is a string
    # and not a foreign key. The collection name is fixed at profile creation.
    knowledge_product_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    knowledge_product_name: Mapped[str | None] = mapped_column(String, nullable=True)
    qdrant_collection: Mapped[str] = mapped_column(String, nullable=False)
    # A synthetic profile is created with a name and a description only. It resolves the
    # Dataset Fabric profile of its Knowledge Product once, and its versions inherit it.
    fabric_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_profiles.id", ondelete="SET NULL"), nullable=True
    )
    # The pipeline whose collected conversations this profile validates. NULL means "yet
    # to be linked", which is a real state: datasets are authored before a pipeline exists.
    pipeline_slug: Mapped[str | None] = mapped_column(String, nullable=True)
    # A snapshot of the pipeline name, so the page renders without the ingestion service.
    pipeline_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["SyntheticDatasetVersion"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class SyntheticDatasetVersion(Base):
    __tablename__ = "synthetic_dataset_versions"
    __table_args__ = (UniqueConstraint("profile_id", "version_no", name="uq_synthetic_version_no"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("synthetic_dataset_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # queued -> running -> completed | failed
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="queued")
    # The request body, kept whole so a run can be repeated.
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # The shape the page polls: phase, contexts_done, rows_single, ...
    progress: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # The Dataset Fabric profile the produced datasets belong to. Optional: without it the
    # rows exist but Offline Evaluation cannot select them.
    fabric_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_profiles.id", ondelete="SET NULL"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # One version per profile may be active.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    row_count_single: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    row_count_multi: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile: Mapped["SyntheticDatasetProfile"] = relationship(back_populates="versions")
