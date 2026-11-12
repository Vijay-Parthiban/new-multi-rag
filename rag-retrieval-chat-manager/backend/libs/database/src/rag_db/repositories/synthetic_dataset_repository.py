"""Reads and writes for Synthetic Dataset Creator profiles and their versions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from rag_db.models.dataset_profile import DatasetProfile
from rag_db.models.evaluation import GoldenDataset, GoldenDatasetItem
from rag_db.models.synthetic_dataset import (
    SyntheticDatasetProfile,
    SyntheticDatasetVersion,
)


class SyntheticDatasetRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Profiles ───────────────────────────────────────────────────────────

    def list_profiles(
        self, *, source: str | None = None, knowledge_product_id: str | None = None
    ) -> list[SyntheticDatasetProfile]:
        """Oldest first: a profile keeps its place in the list as versions are added."""
        query = self._session.query(SyntheticDatasetProfile)
        if source:
            query = query.filter(SyntheticDatasetProfile.source == source)
        if knowledge_product_id:
            query = query.filter(
                SyntheticDatasetProfile.knowledge_product_id == knowledge_product_id
            )
        return query.order_by(
            SyntheticDatasetProfile.created_at.asc(), SyntheticDatasetProfile.id.asc()
        ).all()

    def get_profile(self, profile_id: uuid.UUID) -> SyntheticDatasetProfile | None:
        return self._session.get(SyntheticDatasetProfile, profile_id)

    def get_profile_by_name(
        self, name: str, source: str = "synthetic"
    ) -> SyntheticDatasetProfile | None:
        return (
            self._session.query(SyntheticDatasetProfile)
            .filter(
                SyntheticDatasetProfile.name == name.strip(),
                SyntheticDatasetProfile.source == source,
            )
            .one_or_none()
        )

    def create_profile(self, **fields: Any) -> SyntheticDatasetProfile:
        profile = SyntheticDatasetProfile(**fields)
        self._session.add(profile)
        self._session.flush()
        return profile

    def update_profile(self, profile_id: uuid.UUID, **fields: Any) -> SyntheticDatasetProfile | None:
        profile = self.get_profile(profile_id)
        if not profile:
            return None
        for key, value in fields.items():
            setattr(profile, key, value)
        self._session.flush()
        return profile

    def first_fabric_profile(self, knowledge_product_id: str) -> DatasetProfile | None:
        """The Dataset Fabric profile a synthetic profile writes into.

        A product may hold more than one. The oldest is taken, once, when the synthetic
        profile is created, so no run ever asks the user to choose one.
        """
        return (
            self._session.query(DatasetProfile)
            .filter(DatasetProfile.knowledge_product_id == knowledge_product_id)
            .order_by(DatasetProfile.created_at.asc())
            .first()
        )

    def get_fabric_profile(self, fabric_profile_id: uuid.UUID) -> DatasetProfile | None:
        return self._session.get(DatasetProfile, fabric_profile_id)

    def delete_profile(self, profile_id: uuid.UUID) -> None:
        profile = self.get_profile(profile_id)
        if profile:
            self._session.delete(profile)
            self._session.flush()

    # ── Versions ───────────────────────────────────────────────────────────

    def count_versions(self, profile_id: uuid.UUID) -> int:
        return (
            self._session.query(SyntheticDatasetVersion)
            .filter(SyntheticDatasetVersion.profile_id == profile_id)
            .count()
        )

    def list_versions(self, profile_id: uuid.UUID) -> list[SyntheticDatasetVersion]:
        return (
            self._session.query(SyntheticDatasetVersion)
            .filter(SyntheticDatasetVersion.profile_id == profile_id)
            .order_by(SyntheticDatasetVersion.version_no.desc())
            .all()
        )

    def get_version(self, version_id: uuid.UUID) -> SyntheticDatasetVersion | None:
        return self._session.get(SyntheticDatasetVersion, version_id)

    def next_version_no(self, profile_id: uuid.UUID) -> int:
        highest = (
            self._session.query(func.max(SyntheticDatasetVersion.version_no))
            .filter(SyntheticDatasetVersion.profile_id == profile_id)
            .scalar()
        )
        return (highest or 0) + 1

    def create_version(self, **fields: Any) -> SyntheticDatasetVersion:
        version = SyntheticDatasetVersion(**fields)
        self._session.add(version)
        self._session.flush()
        return version

    def update_version(
        self, version_id: uuid.UUID, **fields: Any
    ) -> SyntheticDatasetVersion | None:
        version = self.get_version(version_id)
        if not version:
            return None
        for key, value in fields.items():
            setattr(version, key, value)
        self._session.flush()
        return version

    def activate_version(self, version_id: uuid.UUID) -> SyntheticDatasetVersion | None:
        """Make one version the active one of its profile."""
        version = self.get_version(version_id)
        if version is None:
            return None
        self._session.query(SyntheticDatasetVersion).filter(
            SyntheticDatasetVersion.profile_id == version.profile_id,
            SyntheticDatasetVersion.id != version.id,
        ).update({SyntheticDatasetVersion.is_active: False}, synchronize_session=False)
        version.is_active = True
        self._session.flush()
        return version

    def delete_version(self, version_id: uuid.UUID) -> None:
        version = self.get_version(version_id)
        if version:
            self._session.delete(version)
            self._session.flush()

    def datasets_for_version(self, version_id: uuid.UUID) -> list[GoldenDataset]:
        return (
            self._session.query(GoldenDataset)
            .filter(GoldenDataset.version_id == version_id)
            .order_by(GoldenDataset.created_at.asc())
            .all()
        )

    def clear_dataset_items(self, dataset_id: uuid.UUID) -> None:
        """Remove a dataset's rows.

        RQ re-delivers a job whose worker died, so `run_synthesis` may start twice for one
        version. It clears the rows first; without this the second run appends a duplicate
        set to a dataset that already holds one.
        """
        self._session.query(GoldenDatasetItem).filter(
            GoldenDatasetItem.dataset_id == dataset_id
        ).delete(synchronize_session=False)
        self._session.flush()
