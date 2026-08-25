"""Time-window policy for snapshots of newly discovered public works."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


EARLY_WINDOW = timedelta(hours=48)
MONITORING_WINDOW = timedelta(days=7)
DISCOVERY_INTERVAL = timedelta(hours=4)
EARLY_INTERVAL = timedelta(hours=4)
LATE_INTERVAL = timedelta(days=1)


@dataclass(frozen=True)
class SnapshotPolicy:
    phase: str
    due: bool
    next_due_at: datetime | None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def evaluate_snapshot_policy(
    *,
    published_at: datetime,
    last_snapshot_at: datetime | None,
    now: datetime,
) -> SnapshotPolicy:
    """Return whether an already discovered work needs another snapshot.

    Discovery itself runs every four hours. The first observation is always
    stored immediately. Further observations are every four hours through the
    first 48 hours, daily through day seven, then stop.
    """
    published = _as_utc(published_at)
    observed_now = _as_utc(now)
    age = max(observed_now - published, timedelta(0))

    if last_snapshot_at is None:
        return SnapshotPolicy(phase="first_seen", due=True, next_due_at=observed_now)
    if age >= MONITORING_WINDOW:
        return SnapshotPolicy(phase="stopped", due=False, next_due_at=None)

    interval = EARLY_INTERVAL if age <= EARLY_WINDOW else LATE_INTERVAL
    phase = "early_4h" if age <= EARLY_WINDOW else "daily"
    next_due_at = _as_utc(last_snapshot_at) + interval
    return SnapshotPolicy(
        phase=phase,
        due=observed_now >= next_due_at,
        next_due_at=next_due_at,
    )
