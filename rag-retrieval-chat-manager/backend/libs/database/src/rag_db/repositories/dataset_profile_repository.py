"""Reads and writes for Dataset Fabric profiles."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session, selectinload

from rag_db.models.dataset_profile import DatasetProfile
from rag_db.models.evaluation import GoldenDataset


class DatasetProfileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_profiles(self, *, pipeline_slug: str | None = None) -> list[DatasetProfile]:
        """Profiles with their datasets, newest first.

        A profile with no pipeline is returned by the unfiltered call and by no filtered
        one, which is what the Offline Evaluation page needs: only a profile linked to the
        selected pipeline may appear there.
        """
        query = self._session.query(DatasetProfile).options(
            selectinload(DatasetProfile.datasets)
        )
        if pipeline_slug:
            query = query.filter(DatasetProfile.pipeline_slug == pipeline_slug)
        return query.order_by(DatasetProfile.created_at.desc()).all()

    def get(self, profile_id: uuid.UUID) -> DatasetProfile | None:
        return (
            self._session.query(DatasetProfile)
            .options(selectinload(DatasetProfile.datasets))
            .filter(DatasetProfile.id == profile_id)
            .one_or_none()
        )

    def get_by_name(self, name: str) -> DatasetProfile | None:
        return (
            self._session.query(DatasetProfile)
            .filter(DatasetProfile.name == name.strip())
            .one_or_none()
        )

    def create(self, **fields: Any) -> DatasetProfile:
        profile = DatasetProfile(**fields)
        self._session.add(profile)
        self._session.flush()
        return profile

    def delete(self, profile: DatasetProfile) -> list[GoldenDataset]:
        """Remove the profile and return its datasets so the caller can drop the files."""
        from rag_db.repositories.evaluation_repository import EvaluationRepository

        datasets = list(profile.datasets or [])
        repo = EvaluationRepository(self._session)
        for dataset in datasets:
            repo.delete_dataset(dataset.id)
        self._session.delete(profile)
        self._session.flush()
        return datasets
