"""Raccolta dei warning fiscali emessi durante il calcolo."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

# Livelli
INFO = "INFO"
WARN = "WARN"
CRITICAL = "CRITICAL"


@dataclass
class Warning:
    level: str
    code: str
    message: str


@dataclass
class WarningCollector:
    items: List[Warning] = field(default_factory=list)

    def add(self, level: str, code: str, message: str) -> None:
        self.items.append(Warning(level, code, message))

    def info(self, code: str, message: str) -> None:
        self.add(INFO, code, message)

    def warn(self, code: str, message: str) -> None:
        self.add(WARN, code, message)

    def critical(self, code: str, message: str) -> None:
        self.add(CRITICAL, code, message)

    def has_critical(self) -> bool:
        return any(w.level == CRITICAL for w in self.items)

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def __bool__(self):
        # Un collector esiste sempre: evita che uno vuoto risulti "falsy" e venga
        # scartato dal pattern ``warnings = warnings or WarningCollector()``,
        # perdendo i warning accumulati.
        return True
