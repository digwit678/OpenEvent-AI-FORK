from __future__ import annotations

from pathlib import Path

import pytest

from tests.flows.run_yaml_flow import run_suite_file


def pytest_collect_file(parent, path):
    pathlib_path = Path(str(path))
    if pathlib_path.suffix.lower() not in {".yaml", ".yml"}:
        return None
    specified = parent.config.invocation_params.args or ()
    target = pathlib_path.resolve()
    resolved_args = set()
    for arg in specified:
        try:
            candidate = Path(arg)
        except TypeError:
            continue
        if candidate.suffix.lower() not in {".yaml", ".yml"}:
            continue
        try:
            resolved = candidate.resolve()
        except FileNotFoundError:
            continue
        resolved_args.add(resolved)
    if resolved_args and target in resolved_args:
        return FlowSpecFile.from_parent(parent, path=pathlib_path)
    return None


class FlowSpecFile(pytest.File):
    def collect(self):
        yield FlowSpecItem.from_parent(self, name=self.path.name)


class FlowSpecItem(pytest.Item):
    def runtest(self):
        run_suite_file(Path(str(self.path)))


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = str(item.fspath)
        if "tests/_legacy" in path or "tests/specs/legacy" in path:
            item.add_marker(pytest.mark.legacy)
            item.add_marker(
                pytest.mark.xfail(
                    reason="Legacy v3 alignment suite is retained for reference; v4 workflow diverges in behaviour.",
                    strict=False,
                )
            )
        else:
            item.add_marker(pytest.mark.v4)
