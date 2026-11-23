def parse_id(value):
    """Query/form value -> int id, or None if missing/invalid (ignore bad filters instead of 500)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
