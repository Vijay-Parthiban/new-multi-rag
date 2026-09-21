from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_db.models.prompt import PromptTemplate


class PromptRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        name: str,
        content: str,
        description: str | None = None,
    ) -> PromptTemplate:
        template = PromptTemplate(name=name, content=content, description=description)
        self._session.add(template)
        self._session.flush()
        return template

    def get(self, template_id: uuid.UUID) -> PromptTemplate | None:
        return self._session.get(PromptTemplate, template_id)

    def get_by_name(self, name: str) -> PromptTemplate | None:
        return self._session.scalars(select(PromptTemplate).where(PromptTemplate.name == name)).first()

    def list(self) -> list[PromptTemplate]:
        stmt = select(PromptTemplate).order_by(PromptTemplate.name)
        return list(self._session.scalars(stmt).all())

    def update(self, template_id: uuid.UUID, **updates: Any) -> PromptTemplate | None:
        template = self.get(template_id)
        if not template:
            return None
        for key, value in updates.items():
            if hasattr(template, key):
                setattr(template, key, value)
        self._session.flush()
        return template

    def delete(self, template_id: uuid.UUID) -> bool:
        template = self.get(template_id)
        if not template:
            return False
        self._session.delete(template)
        self._session.flush()
        return True
