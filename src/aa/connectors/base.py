from __future__ import annotations

from abc import ABC, abstractmethod


class BaseConnector(ABC):
    """Abstract base class for all source connectors."""

    source_name: str

    @abstractmethod
    async def authenticate(self) -> None:
        ...

    @abstractmethod
    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        ...
