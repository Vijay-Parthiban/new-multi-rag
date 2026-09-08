from __future__ import annotations

import uuid
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rag_db.models.guardrails import GuardrailsConfig, GuardrailsTrace


class GuardrailsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_config(
        self,
        name: str,
        guards: list[str],
        mode: str = "both",
        description: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> GuardrailsConfig:
        config = GuardrailsConfig(
            name=name,
            guards=guards,
            mode=mode,
            description=description,
            settings=settings or {},
        )
        self._session.add(config)
        self._session.flush()
        return config

    def get_config(self, config_id: uuid.UUID) -> GuardrailsConfig | None:
        return self._session.get(GuardrailsConfig, config_id)

    def list_configs(self, active_only: bool = False) -> list[GuardrailsConfig]:
        stmt = select(GuardrailsConfig)
        if active_only:
            stmt = stmt.where(GuardrailsConfig.is_active.is_(True))
        stmt = stmt.order_by(GuardrailsConfig.created_at.desc())
        return list(self._session.scalars(stmt).all())

    def update_config(self, config_id: uuid.UUID, **updates: Any) -> GuardrailsConfig | None:
        config = self.get_config(config_id)
        if not config:
            return None
        for key, value in updates.items():
            if hasattr(config, key):
                setattr(config, key, value)
        self._session.flush()
        return config

    def delete_config(self, config_id: uuid.UUID) -> bool:
        config = self.get_config(config_id)
        if not config:
            return False
        self._session.delete(config)
        self._session.flush()
        return True

    def record_trace(
        self,
        *,
        config_id: uuid.UUID | None,
        query: str,
        response: str | None = None,
        blocked: bool = False,
        blocked_by_guard: str | None = None,
        blocked_on: str | None = None,
        guard_results: dict[str, Any] | None = None,
        chat_message_id: uuid.UUID | None = None,
    ) -> GuardrailsTrace:
        trace = GuardrailsTrace(
            config_id=config_id,
            query=query,
            response=response,
            blocked=blocked,
            blocked_by_guard=blocked_by_guard,
            blocked_on=blocked_on,
            guard_results=guard_results or {},
            chat_message_id=chat_message_id,
        )
        self._session.add(trace)
        self._session.flush()
        return trace

    def list_traces(
        self,
        guard: str | None = None,
        blocked: bool | None = None,
        config_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[GuardrailsTrace], int]:
        stmt = select(GuardrailsTrace)
        if guard:
            stmt = stmt.where(GuardrailsTrace.blocked_by_guard == guard)
        if blocked is not None:
            stmt = stmt.where(GuardrailsTrace.blocked == blocked)
        if config_id:
            stmt = stmt.where(GuardrailsTrace.config_id == config_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self._session.scalar(count_stmt) or 0

        stmt = stmt.order_by(GuardrailsTrace.created_at.desc()).offset(offset).limit(limit)
        traces = list(self._session.scalars(stmt).all())
        return traces, total

    def get_stats(self) -> dict[str, Any]:
        total_stmt = select(func.count(GuardrailsTrace.id))
        total_requests = self._session.scalar(total_stmt) or 0

        blocked_stmt = select(func.count(GuardrailsTrace.id)).where(GuardrailsTrace.blocked.is_(True))
        blocked_requests = self._session.scalar(blocked_stmt) or 0

        passed_requests = total_requests - blocked_requests
        block_rate = (blocked_requests / total_requests) if total_requests > 0 else 0.0

        per_guard_stmt = (
            select(GuardrailsTrace.blocked_by_guard, func.count(GuardrailsTrace.id))
            .where(GuardrailsTrace.blocked.is_(True))
            .group_by(GuardrailsTrace.blocked_by_guard)
        )
        rows = self._session.execute(per_guard_stmt).all()
        per_guard = {row[0] or "unknown": row[1] for row in rows}

        return {
            "total_requests": total_requests,
            "blocked_requests": blocked_requests,
            "passed_requests": passed_requests,
            "block_rate": block_rate,
            "per_guard": per_guard,
        }
