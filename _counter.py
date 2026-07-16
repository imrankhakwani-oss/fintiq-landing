"""
Persistent in-process search counter for Fintiq.
This module is imported once per Railway process lifetime.
Python's module cache (sys.modules) keeps it alive across
all Streamlit reruns, refreshes, logouts, and logins.
Resets only on Railway redeploy.
"""
from collections import defaultdict
from datetime import datetime

# (user_id, "YYYY-MM") -> int
_counts: dict = defaultdict(int)


def _key(user_id: str) -> tuple:
    return (user_id, datetime.now().strftime("%Y-%m"))


def get(user_id: str) -> int:
    """Return current monthly search count for user."""
    return _counts[_key(user_id)]


def increment(user_id: str) -> int:
    """Increment and return new count."""
    k = _key(user_id)
    _counts[k] += 1
    return _counts[k]


def seed(user_id: str, count: int):
    """Seed the counter from DB (call once after DB read succeeds)."""
    k = _key(user_id)
    # Only seed if current in-memory value is lower (DB is source of truth)
    if count > _counts[k]:
        _counts[k] = count


def is_seeded(user_id: str) -> bool:
    """True if we've already attempted to seed from DB this process."""
    return _key(user_id) in _counts and _counts[_key(user_id)] >= 0
