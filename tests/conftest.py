from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = str(item.fspath)
        if "tests/_legacy" in path:
            item.add_marker(pytest.mark.legacy)
            item.add_marker(
                pytest.mark.xfail(
                    reason="Legacy v3 alignment suite is retained for reference; v4 workflow diverges in behaviour.",
                    strict=False,
                )
            )
        else:
            item.add_marker(pytest.mark.v4)
