"""Shared symlink-capability probe for tests that exercise real symlinks.

Deliberately not named conftest.py: tests/test_skills/conftest.py already
claims that bare module name, and neither tests/ nor its subdirectories
carry __init__.py, so two files both named "conftest" would race for the
same entry in sys.modules — whichever pytest imports first wins that name
for the rest of the session, and any other file's `from conftest import X`
resolves to whichever one won, not necessarily the one in the same
directory. A uniquely-named module sidesteps that entirely.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


def _symlinks_supported() -> bool:
    """Probe whether this process can actually create filesystem symlinks.

    Windows requires SeCreateSymbolicLinkPrivilege — Developer Mode enabled,
    or an elevated process — to call os.symlink(); without it every symlink
    test fails identically with OSError: [WinError 1314]. Detected with a
    real create-in-tempdir probe rather than a bare `sys.platform == "win32"`
    check: Windows with Developer Mode on (or running elevated) supports
    symlinks fine, and gating on OS name alone would skip tests that could
    actually run there.
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.write_text("x", encoding="utf-8")
            (Path(tmp) / "link").symlink_to(target)
        return True
    except OSError:
        return False


#: Shared skip condition for tests that exercise real symlink creation.
#: Usage: @pytest.mark.skipif(not SYMLINKS_SUPPORTED, reason="...")
SYMLINKS_SUPPORTED = _symlinks_supported()
