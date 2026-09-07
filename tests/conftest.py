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
