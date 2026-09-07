from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_PYTEST_STATE_ROOT = Path(tempfile.gettempdir()) / f"agentos-pytest-{os.getpid()}"

os.environ.setdefault("AGENTOS_STATE_DIR", str(_PYTEST_STATE_ROOT / "state"))
os.environ.setdefault("AGENTOS_LOG_DIR", str(_PYTEST_STATE_ROOT / "logs"))
os.environ.setdefault("AGENTOS_TURN_CALL_LOG", "0")
# OpenCAP price lookups refresh their catalog over the network when the cache
# is cold. Default tests must stay offline; tests that exercise the refresh
# opt back in with monkeypatch.setenv.
os.environ.setdefault("AGENTOS_OPENCAP_LIVE_PRICING", "0")


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
