import os


def strict_user() -> bool:
    return (os.environ.get("AGENT_STRICT_USER") or "").strip().lower() in ("1", "true", "yes")
