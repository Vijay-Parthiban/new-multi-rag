from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_api.main import create_app


@pytest.fixture
def client():
    # The lifespan builds a pipeline, a retriever, and a Redis queue. These routes need
    # only the settings object, so it is set directly and the lifespan stays unrun.
    from rag_shared.config import get_settings

    app = create_app()
    app.state.settings = get_settings()
    return TestClient(app)


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        pass

    def flush(self):
        pass

    def delete(self, obj):
        pass

    def rollback(self):
        pass


def _profile(knowledge_product_id: str = "kp-1") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name="Resume profile",
        description=None,
        knowledge_product_id=knowledge_product_id,
        knowledge_product_name="Resumes",
        qdrant_collection="kp_resumes",
        version_count=0,
        created_at=None,
        updated_at=None,
    )


def test_profile_needs_an_enabled_vector_destination(client):
    repo = MagicMock()
    repo.get_profile_by_name.return_value = None

    with (
        patch("rag_api.routes.synthetic_datasets._session_factory", return_value=_FakeSession),
        patch(
            "rag_db.repositories.synthetic_dataset_repository.SyntheticDatasetRepository",
            return_value=repo,
        ),
        patch(
            "rag_api.routes.synthetic_datasets._knowledge_product",
            AsyncMock(
                return_value={
                    "name": "Resumes",
                    "destinations": [
                        {
                            "destination_type": "vector_qdrant",
                            "enabled": False,
                            "config": {"collection_name": "kp_resumes"},
                        }
                    ],
                }
            ),
        ),
    ):
        response = client.post(
            "/api/synthetic-datasets/profiles",
            json={"name": "Resume profile", "knowledge_product_id": "kp-1"},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "NO_VECTOR_DESTINATION"


def test_version_rejects_an_unknown_kind(client):
    response = client.post(
        f"/api/synthetic-datasets/profiles/{uuid4()}/versions",
        json={"kinds": ["bogus"], "single": {}, "model": "gpt-4o-mini"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_KIND"


def test_version_rejects_one_turn(client):
    response = client.post(
        f"/api/synthetic-datasets/profiles/{uuid4()}/versions",
        json={"kinds": ["multi_turn"], "multi": {"rows": 2, "turns": 1}, "model": "m"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_TURNS"


def test_version_refuses_a_number_already_used(client):
    profile = _profile()
    repo = MagicMock()
    repo.get_profile.return_value = profile
    repo.list_versions.return_value = [SimpleNamespace(version_no=1)]
    body = {"kinds": ["single_turn"], "single": {}, "model": "gpt-4o-mini", "version_no": 1}

    with (
        patch("rag_api.routes.synthetic_datasets._session_factory", return_value=_FakeSession),
        patch(
            "rag_db.repositories.synthetic_dataset_repository.SyntheticDatasetRepository",
            return_value=repo,
        ),
    ):
        response = client.post(
            f"/api/synthetic-datasets/profiles/{profile.id}/versions", json=body
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "VERSION_NO_TAKEN"


def test_profile_with_versions_cannot_be_deleted(client):
    profile = _profile()
    repo = MagicMock()
    repo.get_profile.return_value = profile
    repo.count_versions.return_value = 1

    with (
        patch("rag_api.routes.synthetic_datasets._session_factory", return_value=_FakeSession),
        patch(
            "rag_db.repositories.synthetic_dataset_repository.SyntheticDatasetRepository",
            return_value=repo,
        ),
    ):
        response = client.delete(f"/api/synthetic-datasets/profiles/{profile.id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PROFILE_HAS_VERSIONS"


def test_a_version_without_a_model_is_refused(client):
    body = {"kinds": ["single_turn"], "single": {}, "model": ""}
    response = client.post(f"/api/synthetic-datasets/profiles/{uuid4()}/versions", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "MODEL_NOT_CONFIGURED"


def _version(kind: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        profile_id=uuid4(),
        version_no=1,
        description=None,
        status="completed",
        config={},
        progress={},
        fabric_profile_id=None,
    )


def test_adding_a_dataset_this_version_already_has_is_refused(client):
    version = _version()
    repo = MagicMock()
    repo.get_version.return_value = version
    repo.datasets_for_version.return_value = [SimpleNamespace(id=uuid4(), kind="single_turn")]

    with (
        patch("rag_api.routes.synthetic_datasets._session_factory", return_value=_FakeSession),
        patch(
            "rag_db.repositories.synthetic_dataset_repository.SyntheticDatasetRepository",
            return_value=repo,
        ),
    ):
        response = client.post(
            f"/api/synthetic-datasets/versions/{version.id}/datasets",
            json={"kind": "single_turn", "config": {}},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DATASET_EXISTS"


def test_editing_a_dataset_that_does_not_exist_is_refused(client):
    version = _version()
    repo = MagicMock()
    repo.get_version.return_value = version
    repo.datasets_for_version.return_value = []

    with (
        patch("rag_api.routes.synthetic_datasets._session_factory", return_value=_FakeSession),
        patch(
            "rag_db.repositories.synthetic_dataset_repository.SyntheticDatasetRepository",
            return_value=repo,
        ),
    ):
        response = client.patch(
            f"/api/synthetic-datasets/versions/{version.id}/datasets/multi_turn",
            json={"config": {}},
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DATASET_NOT_FOUND"


def test_deleting_a_dataset_that_does_not_exist_is_refused(client):
    version = _version()
    repo = MagicMock()
    repo.get_version.return_value = version
    repo.datasets_for_version.return_value = []

    with (
        patch("rag_api.routes.synthetic_datasets._session_factory", return_value=_FakeSession),
        patch(
            "rag_db.repositories.synthetic_dataset_repository.SyntheticDatasetRepository",
            return_value=repo,
        ),
    ):
        response = client.delete(
            f"/api/synthetic-datasets/versions/{version.id}/datasets/single_turn"
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DATASET_NOT_FOUND"


def test_a_version_needs_a_config_for_every_kind_it_starts_with(client):
    response = client.post(
        f"/api/synthetic-datasets/profiles/{uuid4()}/versions",
        json={"kinds": ["single_turn", "multi_turn"], "single": {}, "model": "m"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "MISSING_CONFIG"
