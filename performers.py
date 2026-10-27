from __future__ import annotations


def performer_name(user) -> str:
    """Return who entered the transaction, taken straight from the Telegram sender.

    No hard-coded mapping: we simply document the sender's @username. Falls back to the
    display name, then the numeric id, when a username isn't set.

    ``user`` is a telegram.User (or None).
    """
    if user is None:
        return ""
    username = getattr(user, "username", None)
    if username:
        return f"@{username}"
    parts = [getattr(user, "first_name", None), getattr(user, "last_name", None)]
    name = " ".join(p for p in parts if p)
    if name:
        return name
    uid = getattr(user, "id", None)
    return str(uid) if uid is not None else ""
