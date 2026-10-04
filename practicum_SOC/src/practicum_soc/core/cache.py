"""Caché por instancia, protegida por lock y limitada por TTL, entradas y bytes."""

from __future__ import annotations

import copy
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field


class CacheSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ttl_seconds: float = Field(default=5, gt=0, le=60)
    maximum_entries: int = Field(default=32, ge=1, le=128)
    maximum_payload_bytes: int = Field(default=1048576, ge=1024, le=8388608)

    @classmethod
    def from_file(cls, path: Path) -> CacheSettings:
        return (
            cls.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else cls()
        )


class BoundedTTLCache:
    """Solo admite resultados serializables, nunca conexiones o entidades crudas.

    El presupuesto cuenta bytes UTF-8 del payload y de la clave; las entradas
    también están limitadas para acotar el overhead de objetos Python.
    """

    def __init__(self, settings: CacheSettings, *, clock: Callable[[], float] = time.monotonic):
        self.settings = settings
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, int, object]] = OrderedDict()
        self._payload_bytes = 0
        self._lock = RLock()

    def _remove(self, key: str) -> None:
        _, size, _ = self._entries.pop(key)
        self._payload_bytes -= size

    def _expire(self) -> None:
        now = self._clock()
        for key, (deadline, _, _) in list(self._entries.items()):
            if deadline <= now:
                self._remove(key)

    def get(self, key: str):
        with self._lock:
            self._expire()
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return copy.deepcopy(entry[2])

    def put(self, key: str, value: object) -> None:
        payload = copy.deepcopy(value)
        size = len(key.encode()) + len(json.dumps(payload, default=str).encode())
        with self._lock:
            self._expire()
            if key in self._entries:
                self._remove(key)
            if size > self.settings.maximum_payload_bytes:
                return
            while self._entries and (
                len(self._entries) >= self.settings.maximum_entries
                or self._payload_bytes + size > self.settings.maximum_payload_bytes
            ):
                self._remove(next(iter(self._entries)))
            self._entries[key] = (self._clock() + self.settings.ttl_seconds, size, payload)
            self._payload_bytes += size

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._payload_bytes = 0

    @property
    def payload_bytes(self) -> int:
        with self._lock:
            self._expire()
            return self._payload_bytes

    def __len__(self) -> int:
        with self._lock:
            self._expire()
            return len(self._entries)
