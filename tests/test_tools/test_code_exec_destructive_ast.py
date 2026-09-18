"""Tests for AST-based detection of destructive operations in code_exec (Issue #848).

Verifies that static regex evasion techniques (getattr, string concatenation,
__import__, importlib, exec/eval, wildcard imports, and import aliasing)
are accurately caught without false positives on benign code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentos.tools.builtin.code_exec import _check_code_destructive


@pytest.mark.parametrize(
    ("code", "expected_keyword"),
    [
        # Concatenated strings in getattr
        ('import os; getattr(os, "rem" + "ove")("/tmp/x")', "remove"),
        ('import os; getattr(os, "un" + "link")("/tmp/x")', "unlink"),
        ('import os; getattr(os, "rm" + "dir")("/tmp/x")', "rmdir"),
        ('import shutil; getattr(shutil, "rm" + "tree")("/tmp/x")', "rmtree"),
        # f-strings in getattr
        ('import os; getattr(os, f"{\'rem\'}ove")("/tmp/x")', "remove"),
        # Dynamic __import__
        ('__import__("os").remove("/tmp/x")', "remove"),
        ('__import__("os").unlink("/tmp/x")', "unlink"),
        ('__import__("shutil").rmtree("/tmp/x")', "rmtree"),
        # Dynamic importlib.import_module
        ('import importlib; importlib.import_module("os").remove("/tmp/x")', "remove"),
        ('import importlib; importlib.import_module("shutil").rmtree("/tmp/x")', "rmtree"),
        # exec / eval with nested destructive code
        ("exec(\"os.remove('/tmp/x')\")", "remove"),
        ("eval(\"os.remove('/tmp/x')\")", "remove"),
        ('exec(\'getattr(os, "rem" + "ove")("/tmp/x")\')', "remove"),
        # Wildcard imports
        ("from os import *; remove('/tmp/x')", "remove"),
        ("from os import *; unlink('/tmp/x')", "unlink"),
        ("from shutil import *; rmtree('/tmp/x')", "rmtree"),
        # Aliased imports
        ("from os import remove as delete_file; delete_file('/tmp/x')", "remove"),
        ("from shutil import rmtree as nukedir; nukedir('/tmp/x')", "rmtree"),
        ("import os as my_os; my_os.remove('/tmp/x')", "remove"),
        ("import shutil as s; s.rmtree('/tmp/x')", "rmtree"),
        # Path methods via getattr
        ('from pathlib import Path; getattr(Path("/tmp/x"), "unlink")()', "unlink"),
        ('from pathlib import Path; getattr(Path("/tmp/x"), "rmdir")()', "rmdir"),
        # Subprocess list & tuple invocation of rm
        ('import subprocess; subprocess.run(["rm", "-rf", "/tmp/x"])', "subprocess"),
        ('import subprocess as sp; sp.call(["rmdir", "/tmp/x"])', "subprocess"),
        ('import subprocess; subprocess.run(("rm", "-rf", "/tmp/x"))', "subprocess"),
        ('import subprocess as sp; sp.call(("rmdir", "/tmp/x"))', "subprocess"),
        # Windows deletion commands in subprocess and os.system
        (
            r'import subprocess; subprocess.run(["cmd.exe", "/c", "del", "C:\\tmp\\x"])',
            "subprocess",
        ),
        (
            r'import subprocess; subprocess.run(("cmd.exe", "/c", "del", "C:\\tmp\\x"))',
            "subprocess",
        ),
        (
            r'import subprocess; subprocess.run(["cmd.exe", "/c", "erase", "C:\\tmp\\x"])',
            "subprocess",
        ),
        (
            r'import subprocess; subprocess.run(["cmd.exe", "/c", "rd", "/s", "C:\\tmp\\x"])',
            "subprocess",
        ),
        (
            r'import subprocess; subprocess.run(["powershell", "-c", "Remove-Item", "C:\\tmp\\x"])',
            "subprocess",
        ),
        (r'import os; os.system("del C:\\tmp\\x")', "os.system"),
        (r'import os; os.system("erase C:\\tmp\\x")', "os.system"),
        (r'import os; os.system("rd /s /q C:\\tmp\\x")', "os.system"),
        (r'import os; os.system("powershell Remove-Item C:\\tmp\\x")', "os.system"),
        (r'import os; os.popen("del C:\\tmp\\x")', "os.popen"),
        # Prefixed command deletion calls (sudo, env, nohup, time, nice, xargs)
        ('import subprocess; subprocess.run(["sudo", "rm", "-rf", "/etc"])', "subprocess"),
        ('import os; os.system("sudo rm -rf /etc")', "os.system"),
        ('import subprocess; subprocess.run("sudo rm -rf /etc", shell=True)', "subprocess"),
        ('import os; os.system("env FOO=1 rm -rf /etc")', "os.system"),
        ('import subprocess; subprocess.run(["env", "rm", "-rf", "/etc"])', "subprocess"),
        ('import subprocess; subprocess.run(["xargs", "rm", "-rf"])', "subprocess"),
        ('import os; os.system("time rm -rf /etc")', "os.system"),
        ('import os; os.system("nice rm -rf /etc")', "os.system"),
        ('import subprocess; subprocess.run(["nohup", "rm", "-rf", "/etc"])', "subprocess"),
        ('import subprocess; subprocess.run(["sudo", "-n", "rm", "-rf", "/etc"])', "subprocess"),
        ('import subprocess; subprocess.run(["sudo", "-i", "rm", "-rf", "/etc"])', "subprocess"),
        ('import subprocess; subprocess.run(["sudo", "-E", "rm", "-rf", "/etc"])', "subprocess"),
        ('import subprocess; subprocess.run(["sudo", "-S", "rm", "-rf", "/etc"])', "subprocess"),
        ('import subprocess; subprocess.run(["sudo", "-k", "rm", "-rf", "/etc"])', "subprocess"),
        ('import subprocess; subprocess.run(["env", "-i", "rm", "-rf", "/etc"])', "subprocess"),
        ('import subprocess; subprocess.run(["timeout", "10", "rm", "-rf", "/etc"])', "subprocess"),
        (
            'import subprocess; subprocess.run(["timeout", "-k", "5", "10", "rm", "-rf", "/etc"])',
            "subprocess",
        ),
    ],
)
def test_destructive_ast_evasions_detected(code: str, expected_keyword: str) -> None:
    warning = _check_code_destructive(code)
    assert warning is not None, f"Expected warning for: {code}"
    assert "destructive Python operation detected:" in warning
    assert expected_keyword.lower() in warning.lower()


@pytest.mark.parametrize(
    "code",
    [
        # Standard list.remove should NOT trigger
        "items = [1, 2, 3]\nitems.remove(2)",
        # Set.remove should NOT trigger
        "s = {1, 2, 3}\ns.remove(2)",
        # Benign math/sys/os calls
        "import math\nx = math.sqrt(16)",
        "import os\ncwd = os.getcwd()",
        "import os\nfiles = os.listdir('.')",
        "import shutil\nshutil.copy('a.txt', 'b.txt')",
        "from pathlib import Path\np = Path('a.txt').read_text()",
        # Benign getattr
        "import os\npath_fn = getattr(os, 'getcwd')",
        "getattr(dict, 'get')",
        # Benign non-command occurrences of rd and erase (anchoring negative matrix)
        'import subprocess; subprocess.run(["curl", "-o", "out.bin", "https://cdn.example.com/rd"])',
        'import subprocess; subprocess.run(["psql", "-c", "SELECT * FROM rd"])',
        'import subprocess; subprocess.run(["git", "clone", "https://github.com/acme/rd"])',
        'import subprocess; subprocess.run(["ls"], cwd="/data/rd")',
        'import subprocess; subprocess.run(["node", "script.js", "--mode", "rd"])',
        'import subprocess; subprocess.run(["helm", "install", "rd", "./chart"])',
        'import subprocess; subprocess.check_output(["kubectl", "get", "pods", "-n", "rd"])',
        'import subprocess; subprocess.run(["python", "train.py", "--dataset", "erase-bench"])',
        'import os; os.system("aws s3 cp s3://bucket/rd ./")',
        'import os; os.system("echo rd")',
    ],
)
def test_benign_code_does_not_trigger_warning(code: str) -> None:
    warning = _check_code_destructive(code)
    assert warning is None, f"Unexpected warning for safe code: {warning}"


def test_syntax_error_code_falls_back_to_regex() -> None:
    # Syntax error with os.remove() still caught by regex fallback
    bad_syntax_destructive = "os.remove( unclosed string"
    warning = _check_code_destructive(bad_syntax_destructive)
    assert warning is not None
    assert "os.remove()" in warning

    # Benign syntax error returns None
    bad_syntax_benign = "def foo( unclosed"
    assert _check_code_destructive(bad_syntax_benign) is None


@pytest.mark.parametrize(
    ("code", "expected_keyword"),
    [
        # `compile()` is a code carrier: the source must be scanned like the
        # string literal `exec("…")` already is. Each source below is split so
        # the flat regex pass cannot see the destructive spelling.
        ("exec(compile('os.re' + 'move(\"/etc/x\")', '', 'exec'))", "remove"),
        ("eval(compile('os.re' + 'move(\"/etc/x\")', '', 'eval'))", "remove"),
        ("exec(compile('shutil.rm' + 'tree(\"/etc/x\")', '', 'exec'))", "rmtree"),
        ("exec(compile('os.sys' + 'tem(\"rm -rf /etc/x\")', '', 'exec'))", "os.system"),
        (
            "exec(compile(source='os.re' + 'move(\"/etc/x\")', filename='', mode='exec'))",
            "remove",
        ),
        ("c = compile\nexec(c('os.re' + 'move(\"/etc/x\")', '', 'exec'))", "remove"),
        # `__import__` reached indirectly — the importer itself is fetched
        # dynamically, so the callee is an ast.Call, not a Name/Attribute.
        ("getattr(__builtins__, '__import__')('os').remove('/etc/x')", "remove"),
        ("import builtins; getattr(builtins, '__import__')('shutil').rmtree('/etc/x')", "rmtree"),
        ("import builtins; builtins.__import__('os').unlink('/etc/x')", "unlink"),
        ("getattr(__builtins__, '__imp' + 'ort__')('os').remove('/etc/x')", "remove"),
        # Shell-exec attrs via getattr: `system`, `popen`, and the subprocess
        # entrypoints are not in _ALL_DESTRUCTIVE_NAMES, so the getattr branch
        # skipped them entirely.
        ("import os; getattr(os, 'system')('rm -rf /etc/x')", "os.system"),
        ("import os; getattr(os, 'sys' + 'tem')('rm -rf /etc/x')", "os.system"),
        ("import os; getattr(os, 'popen')('rm -rf /etc/x')", "os.popen"),
        (
            "import subprocess; getattr(subprocess, 'run')(['rm', '-rf', '/etc/x'])",
            "subprocess",
        ),
        (
            "import subprocess; getattr(subprocess, 'Popen')('rm -rf /etc/x')",
            "subprocess",
        ),
        # Combinations of both indirections.
        ("getattr(__import__('os'), 'system')('rm -rf /etc/x')", "os.system"),
        (
            "exec(compile('getattr(os, \"sys\" + \"tem\")(\"rm -rf /etc/x\")', '', 'exec'))",
            "os.system",
        ),
        ('import os; getattr(os, "sys" + "tem")("sudo rm -rf /etc")', "os.system"),
    ],
)
def test_indirect_destructive_calls_detected(code: str, expected_keyword: str) -> None:
    """Indirection must not bypass the gate (residual bypasses of #848/#890)."""
    warning = _check_code_destructive(code)
    assert warning is not None, f"Expected warning for: {code}"
    assert "destructive Python operation detected:" in warning
    assert expected_keyword.lower() in warning.lower()


@pytest.mark.parametrize(
    "code",
    [
        # compile() of harmless source stays allowed.
        "exec(compile('print(1)', '', 'exec'))",
        "exec(compile('x = sum([1, 2, 3])', '', 'exec'))",
        # getattr of a non-destructive attr stays allowed, including the
        # shell-exec attrs when the command itself is harmless.
        "import os; getattr(os, 'getcwd')()",
        "import os; getattr(os, 'system')('echo hi')",
        "import subprocess; getattr(subprocess, 'run')(['ls', '-la'])",
        "getattr(__builtins__, 'len')('abc')",
        # An indirect import that never reaches a destructive call.
        "getattr(__builtins__, '__import__')('json').dumps({'a': 1})",
        "import builtins; builtins.__import__('math').sqrt(16)",
    ],
)
def test_indirect_benign_code_does_not_trigger_warning(code: str) -> None:
    warning = _check_code_destructive(code)
    assert warning is None, f"Unexpected warning for safe code: {warning}"


# ── #2776: PowerShell's ``ri`` alias for Remove-Item ────────────────────────
#
# ``shell_policy`` blocks ``rm``, ``rd`` and ``ri`` -- all three of
# PowerShell's built-in aliases -- but the four copies of the delete-command
# alternation here listed only ``rm`` and ``rd``. An agent whose direct shell
# use was blocked could route ``ri`` through ``os.system`` or ``subprocess``
# and delete without approval. The alternation is now built once from
# ``_SHELL_DELETE_CMDS``; these pin ``ri`` at every entry point, and pin the
# two layers to each other.

from agentos.tools.builtin import code_exec, shell_policy  # noqa: E402


@pytest.mark.parametrize(
    ("code", "expected_keyword"),
    [
        # the issue's three reproductions
        (
            r'import subprocess; subprocess.run(["powershell", "-c", "ri", "C:\\tmp\\x"])',
            "subprocess",
        ),
        (r'import os; os.system("powershell -c ri C:\\tmp\\x")', "os.system"),
        (r'import os; os.system("ri -Recurse -Force C:\\tmp\\x")', "os.system"),
        # every other entry point
        (r'import os; os.popen("ri C:\\tmp\\x")', "os.popen"),
        (r'import subprocess; subprocess.run(["ri", "C:\\tmp\\x"])', "subprocess"),
        (r'import subprocess; subprocess.call("ri C:\\tmp\\x", shell=True)', "subprocess"),
        (
            r'import subprocess; subprocess.Popen(["pwsh", "-nop", "-c", "ri", "C:\\x"])',
            "subprocess",
        ),
        (r'import subprocess; subprocess.check_output("ri -r C:\\x", shell=True)', "subprocess"),
        (r'import subprocess; subprocess.check_call(["cmd", "/c", "ri", "C:\\x"])', "subprocess"),
        # wrappers and separators the prefix already understood for rm/rd
        (r'import os; os.system("sudo ri /tmp/x")', "os.system"),
        (r'import os; os.system("echo a; ri C:\\x")', "os.system"),
        (r'import os; os.system("echo a && ri C:\\x")', "os.system"),
        # case: PowerShell aliases are case-insensitive
        (r'import os; os.system("RI C:\\x")', "os.system"),
        (r'import os; os.system("Ri -Force C:\\x")', "os.system"),
        # the AST evasions the rest of this file exists for, applied to ri
        (r'import os; getattr(os, "system")("ri C:\\x")', "os.system"),
        (r'exec("import os; os.system(\"ri C:\\\\x\")")', "os.system"),
        (r'import subprocess as sp; sp.run(["ri", "C:\\x"])', "subprocess"),
    ],
)
def test_ri_alias_is_detected_at_every_entry_point(code: str, expected_keyword: str) -> None:
    warning = _check_code_destructive(code)

    assert warning is not None, f"ri escaped detection: {code}"
    assert expected_keyword in warning


@pytest.mark.parametrize(
    "code",
    [
        # ri as an argument, not a command
        r'import subprocess; subprocess.run(["helm", "install", "ri", "./chart"])',
        r'import subprocess; subprocess.run(["git", "commit", "-m", "ri"])',
        r'import subprocess; subprocess.run(["kubectl", "get", "pods", "-n", "ri"])',
        r'import os; os.system("grep ri notes.txt")',
        r'import os; os.system("echo ri")',
        # ri as a prefix of a longer name
        r'import os; os.system("python ri.py")',
        r'import os; os.system("ripgrep pattern .")',
        r'import os; os.system("rich-cli README.md")',
        r'import subprocess; subprocess.run(["rig", "--version"])',
        r'import subprocess; subprocess.run(["ritual", "start"])',
        # a Python identifier that merely contains it
        "ri = 3\nprint(ri + 1)",
        "def ri(): return 1\nri()",
    ],
)
def test_ri_as_an_argument_or_a_longer_name_is_not_a_delete(code: str) -> None:
    warning = _check_code_destructive(code)

    assert warning is None, f"false positive on: {code} -> {warning}"


def test_the_delete_alternation_is_built_from_one_set() -> None:
    """Four copies of the same list is how ``ri`` went missing; there is one now."""
    for command in code_exec._SHELL_DELETE_CMDS:
        assert re.search(code_exec._DELETE_CMD_ALTERNATION, command, re.IGNORECASE), command
    source = (Path(code_exec.__file__)).read_text(encoding="utf-8")
    assert source.count("_DELETE_CMD_ALTERNATION") >= 5, "the four sites and the definition"
    assert "rm|rmdir|del" not in source, "no hand-written copy of the alternation remains"


def test_every_remove_item_alias_shell_policy_blocks_is_known_here() -> None:
    """The drift guard between the two layers: a name ``DEFAULT_DENYLIST_WIN``
    anchors as a deletion must be a name ``code_exec`` recognises too, or the
    Python route becomes the bypass for it."""
    anchored = set()
    for pattern in shell_policy.DEFAULT_DENYLIST_WIN:
        if pattern.startswith(shell_policy._WIN_CMD_PREFIX):
            name = pattern[len(shell_policy._WIN_CMD_PREFIX) : -len(shell_policy._WIN_CMD_END)]
            anchored.add(name.lower())

    assert anchored, "the denylist still anchors its short aliases through the prefix"
    assert anchored <= code_exec._SHELL_DELETE_CMDS, anchored - code_exec._SHELL_DELETE_CMDS


def test_remove_item_by_cmdlet_name_still_matches_in_any_case() -> None:
    for spelling in ("Remove-Item", "remove-item", "REMOVE-ITEM"):
        assert _check_code_destructive(f'import os; os.system("{spelling} C:\\\\x")') is not None


def test_the_argv_membership_check_knows_ri() -> None:
    """The list form is checked by membership, not regex; ``ri`` is in the set."""
    assert "ri" in code_exec._SHELL_DELETE_CMDS
    assert _check_code_destructive(r'import subprocess; subprocess.run(["ri"])') is not None
