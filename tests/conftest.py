import os
import sys
import tempfile

import pytest


def _can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as d:
        try:
            os.symlink(d, os.path.join(d, "link"))
            return True
        except OSError:
            return False


def pytest_configure(config):
    config.addinivalue_line("markers", "symlinks: needs to create symlinks (skipped where the account cannot)")
    config.addinivalue_line("markers", "posix: needs a POSIX system (skipped on Windows, with the reason)")


def pytest_collection_modifyitems(config, items):
    if sys.platform != "win32":
        return
    no_links = None if _can_symlink() else pytest.mark.skip(
        reason="this Windows account cannot create symlinks (needs Developer Mode or admin)")
    for item in items:
        if no_links and item.get_closest_marker("symlinks"):
            item.add_marker(no_links)
        m = item.get_closest_marker("posix")
        if m:
            item.add_marker(pytest.mark.skip(reason=m.kwargs.get("reason", "POSIX only")))
