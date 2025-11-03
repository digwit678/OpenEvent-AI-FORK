TZ = "Europe/Zurich"


class freeze_time:
    """Lightweight stand-in for freezegun.freeze_time used in specs tests."""

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False
