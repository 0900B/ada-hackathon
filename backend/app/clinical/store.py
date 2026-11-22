"""The clinical log: an append-only, in-memory list of ClinicalEntry, in the order recorded.

Nothing is ever edited or removed. A correction is a new entry whose `supersedes` names the
entry it replaces; the old one stays in the log. Lookups are indexes over that one list.
Like the rest of the world state this lives in memory on a single event loop, so no locks.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import ClinicalEntry

if TYPE_CHECKING:  # type only: importing app.state at runtime would make a cycle with the later seam
    from ..state import WorldState


class ClinicalLog:
    def __init__(self) -> None:
        self._entries: list[ClinicalEntry] = []  # entry with seq n sits at index n - 1
        self._by_case: dict[str, list[ClinicalEntry]] = {}
        self._by_client: dict[tuple[str, str], ClinicalEntry] = {}
        self._superseded: set[str] = set()

    def append(self, fields: dict[str, Any]) -> ClinicalEntry:
        """Store one entry. `fields` is every ClinicalEntry field except seq and entry_id."""
        seq = len(self._entries) + 1
        # Built (and so validated) before anything changes: a refused entry takes no seq.
        entry = ClinicalEntry(seq=seq, entry_id=f"CE-{seq:05d}", **fields)
        self._entries.append(entry)
        self._by_case.setdefault(entry.case_id, []).append(entry)
        if entry.client_entry_id is not None:
            self._by_client.setdefault((entry.unit, entry.client_entry_id), entry)  # the first one stays
        if entry.supersedes is not None:
            self._superseded.add(entry.supersedes)
        return entry

    def get(self, seq: int) -> ClinicalEntry | None:
        return self._entries[seq - 1] if 1 <= seq <= len(self._entries) else None

    def by_client_id(self, unit: str, client_entry_id: str) -> ClinicalEntry | None:
        """The entry a unit already sent under this id (client ids are only unique per unit)."""
        return self._by_client.get((unit, client_entry_id))

    def for_case(self, case_id: str) -> list[ClinicalEntry]:
        """All entries of one case, in log order (a copy: the log itself cannot be changed through it)."""
        return list(self._by_case.get(case_id, ()))

    def since(self, seq: int = 0, case_id: str | None = None, limit: int = 500) -> list[ClinicalEntry]:
        """Entries after `seq` (oldest first, at most `limit`), optionally only one case's."""
        if limit <= 0:
            return []
        newer = self._entries[max(seq, 0):]
        if case_id is not None:
            newer = [e for e in newer if e.case_id == case_id]
        return newer[:limit]

    def tail(self, n: int) -> list[ClinicalEntry]:
        """The newest `n` entries, oldest first."""
        return self._entries[-n:] if n > 0 else []

    def superseded_ids(self) -> set[str]:
        """Entry ids that a later entry replaced, whether or not that later entry is itself replaced."""
        return set(self._superseded)

    @property
    def last_seq(self) -> int:
        return len(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


def get_log(state: WorldState) -> ClinicalLog:
    """The world's clinical log, created and attached on first use (so a plain WorldState works too)."""
    log = getattr(state, "clinical", None)
    if log is None:
        log = ClinicalLog()
        state.clinical = log
    return log
