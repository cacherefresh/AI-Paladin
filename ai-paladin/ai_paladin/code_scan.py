"""
What a script handed to an interpreter would write, read or run.

Used by the Claude Code PreToolUse hook (ai_paladin/hook.py) for
`python3 -c '...'`, `python3 script.py`, `perl -e`, `node -e` and the like,
including scripts the agent wrote itself a moment earlier. The hook checks
what is found here exactly as if the agent had used the Write tool or typed
the shell command.

Python is parsed (ast): open(..., 'w'), pathlib writes, os / shutil file
calls, and os.system / subprocess commands are read with their arguments,
where those are literal strings or built from literals (concatenation,
f-strings without fields, os.path.join, Path / 'x', a name assigned a
literal). Other languages are scanned for quoted string literals when the
code contains a file-writing call.

LIMIT: this reads code; it does not run it. A path computed at run time
(read from a file, decoded, assembled in a loop) is invisible. The hook is a
hardened guardrail, not a sandbox (docs/ROADMAP.md, section 9).
"""

import ast
import re
import shlex
from typing import List, Optional, Tuple

WRITE, DESTROY = "write", "destroy"

# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

_MODULES = {"os", "shutil", "posix", "pathlib", "io", "codecs", "subprocess"}
# os / shutil function -> [(argument index, kind)]
_FUNCS = {
    "remove": [(0, DESTROY)], "unlink": [(0, DESTROY)],
    "rmdir": [(0, DESTROY)], "removedirs": [(0, DESTROY)],
    "rmtree": [(0, DESTROY)],
    "rename": [(0, DESTROY), (1, WRITE)], "renames": [(0, DESTROY), (1, WRITE)],
    "replace": [(0, DESTROY), (1, WRITE)], "move": [(0, DESTROY), (1, WRITE)],
    "mkdir": [(0, WRITE)], "makedirs": [(0, WRITE)], "chmod": [(0, WRITE)],
    "chown": [(0, WRITE)], "lchown": [(0, WRITE)], "truncate": [(0, WRITE)],
    "utime": [(0, WRITE)], "mkfifo": [(0, WRITE)], "mknod": [(0, WRITE)],
    "symlink": [(1, WRITE)], "link": [(1, WRITE)],
    "copy": [(1, WRITE)], "copy2": [(1, WRITE)], "copyfile": [(1, WRITE)],
    "copytree": [(1, WRITE)], "copymode": [(1, WRITE)],
    "copystat": [(1, WRITE)], "copyfileobj": [],
}
# pathlib.Path methods -> kind for the path itself (+ dest for rename)
_PATH_METHODS = {"write_text": WRITE, "write_bytes": WRITE, "touch": WRITE,
                 "mkdir": WRITE, "chmod": WRITE, "unlink": DESTROY,
                 "rmdir": DESTROY, "rename": DESTROY, "replace": DESTROY,
                 "symlink_to": WRITE, "hardlink_to": WRITE}
_SUBPROCESS = {"run", "call", "check_call", "check_output", "Popen",
               "getoutput", "getstatusoutput"}
_OS_SHELL = {"system", "popen"}
_OS_EXEC = re.compile(r"^(exec|spawn)[lv]p?e?$")
_PATH_CTORS = {"Path", "PurePath", "PosixPath", "PurePosixPath"}


def _dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


class _Py:
    def __init__(self, tree):
        self.tree = tree
        self.names = {}
        for node in ast.walk(tree):                # NAME = <literal>
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                    isinstance(node.targets[0], ast.Name):
                self.names.setdefault(node.targets[0].id, node.value)
        self.writes: List[Tuple[str, str]] = []
        self.shells: List[str] = []
        self.strings: List[str] = []

    def const(self, node, depth=0) -> Optional[str]:
        """The string an expression evaluates to, if built from literals."""
        if depth > 20 or node is None:
            return None
        c = lambda n: self.const(n, depth + 1)              # noqa: E731
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            v = node.value
            return v.decode("utf-8", "replace") if isinstance(v, bytes) else v
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                elif isinstance(v, ast.FormattedValue) and c(v.value) is not None:
                    parts.append(c(v.value))
                else:
                    return None
            return "".join(parts)
        if isinstance(node, ast.BinOp):
            left, right = c(node.left), c(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Div):                 # Path / "x"
                return left.rstrip("/") + "/" + right
            return None
        if isinstance(node, ast.Name) and node.id in self.names:
            return c(self.names[node.id])
        if isinstance(node, ast.Call):
            name = _dotted(node.func).split(".")[-1]
            args = [c(a) for a in node.args]
            if name in _PATH_CTORS | {"join", "str", "fspath", "expanduser",
                                      "abspath", "realpath", "normpath",
                                      "resolve", "absolute", "joinpath"}:
                if isinstance(node.func, ast.Attribute) and name in (
                        "resolve", "expanduser", "absolute") and \
                        _dotted(node.func.value) not in ("os.path", "posixpath"):
                    return c(node.func.value)        # Path(x).expanduser()
                if name == "joinpath" and isinstance(node.func, ast.Attribute):
                    args = [c(node.func.value)] + args
                if args and all(a is not None for a in args):
                    out = args[0]
                    for a in args[1:]:
                        out = a if a.startswith("/") else out.rstrip("/") + "/" + a
                    return out
            if name == "decode" and isinstance(node.func, ast.Attribute):
                return c(node.func.value)
        return None

    def _mode_writes(self, call, mode_pos: int) -> bool:
        mode = None
        if len(call.args) > mode_pos:
            mode = self.const(call.args[mode_pos])
        for kw in call.keywords:
            if kw.arg == "mode":
                mode = self.const(kw.value)
        return mode is not None and any(ch in mode for ch in "wax+")

    def _target(self, node, kind):
        v = self.const(node)
        if v is not None:
            self.writes.append((v, kind))

    def _command(self, node, shell: bool):
        v = self.const(node)
        if v is not None:
            self.shells.append(v)
            return
        if isinstance(node, (ast.List, ast.Tuple)):
            parts = [self.const(e) for e in node.elts]
            if parts and all(p is not None for p in parts):
                self.shells.append(" ".join(shlex.quote(p) for p in parts))

    def visit(self):
        for node in ast.walk(self.tree):
            v = self.const(node) if isinstance(
                node, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.Call)) else None
            if v is not None:
                self.strings.append(v)
            if not isinstance(node, ast.Call):
                continue
            dotted = _dotted(node.func)
            name = dotted.split(".")[-1]
            owner = dotted.split(".")[0] if "." in dotted else ""
            args = node.args
            if (name == "open" and isinstance(node.func, ast.Name)) or \
                    dotted in ("io.open", "codecs.open", "builtins.open"):
                if args and self._mode_writes(node, 1):
                    self._target(args[0], WRITE)
            elif dotted == "os.open" and args:
                flags = ast.dump(args[1]) if len(args) > 1 else ""
                if re.search(r"O_(WRONLY|RDWR|CREAT|TRUNC|APPEND)", flags):
                    self._target(args[0], WRITE)
            elif isinstance(node.func, ast.Attribute) and \
                    owner not in _MODULES and name in set(_PATH_METHODS) | {"open"}:
                recv = node.func.value
                if name == "open":
                    if self._mode_writes(node, 0):
                        self._target(recv, WRITE)
                else:
                    if self.const(recv) is not None and (
                            name not in ("replace",) or
                            isinstance(recv, ast.Call)):
                        self._target(recv, _PATH_METHODS[name])
                        if name in ("rename", "replace") and args:
                            self._target(args[0], WRITE)
            elif name in _FUNCS and (owner in _MODULES or
                                     isinstance(node.func, ast.Name)):
                for pos, kind in _FUNCS[name]:
                    if len(args) > pos:
                        self._target(args[pos], kind)
                for kw in node.keywords:
                    if kw.arg in ("dst", "dest", "destination"):
                        self._target(kw.value, WRITE)
                    if kw.arg in ("path", "src") and _FUNCS[name][:1] and \
                            _FUNCS[name][0][1] == DESTROY:
                        self._target(kw.value, DESTROY)
            elif (owner == "os" and name in _OS_SHELL) or \
                    (owner == "subprocess" and name in _SUBPROCESS) or \
                    (owner == "" and name == "system"):
                if args:
                    self._command(args[0], True)
                for kw in node.keywords:
                    if kw.arg == "args":
                        self._command(kw.value, True)
            elif owner == "os" and _OS_EXEC.match(name) and len(args) > 1:
                rest = args[1] if name[-1:] in ("v", "e") and len(args) == 2 \
                    else ast.List(elts=list(args[1:]), ctx=ast.Load())
                self._command(rest, False)


def python_effects(code: str):
    """(writes [(path, kind)], shell commands [str], strings [str]) for
    Python source, or None if it does not parse."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    py = _Py(tree)
    py.visit()
    return py.writes, py.shells, py.strings


# ---------------------------------------------------------------------------
# anything else: string literals
# ---------------------------------------------------------------------------

_LITERAL = re.compile(r"'((?:[^'\\\n]|\\.){1,4096})'|\"((?:[^\"\\\n]|\\.){1,4096})\"")
WRITE_HINT = re.compile(
    r"open\s*\(|\bwrite|\bunlink|\bremove|rmtree|rmSync|rmdir|\brename"
    r"|\bmove\b|copyFile|copy_file|\bcopy\b|truncate|chmod|chown|symlink"
    r"|mkdir|makedirs|appendFile|writeFile|File\.(write|open|delete)"
    r"|FileUtils|file_put_contents|fopen|\bsystem\s*\(|\bexec\w*\s*\("
    r"|spawn|`|\bqx\b")
DESTROY_HINT = re.compile(r"unlink|remove|rmtree|rmSync|rmdir|rename|\bmove\b"
                          r"|delete|truncate")


def literals(code: str) -> List[str]:
    out = []
    for m in _LITERAL.finditer(code):
        s = m.group(1) if m.group(1) is not None else m.group(2)
        out.append(s.replace("\\/", "/"))
    return out


def path_like(s: str) -> bool:
    s = s.strip()
    if not s or "\n" in s or "://" in s or len(s) > 4096:
        return False
    s = s.lstrip("+<>| ")                     # perl open modes: '>/etc/x'
    return s.startswith(("/", "~", "./", "../", ".")) or "/" in s


def strip_mode(s: str) -> str:
    return s.strip().lstrip("+<>| ").strip()


def effects(code: str, lang: str):
    """(writes [(path, kind)], shell commands [str], strings [str])."""
    if lang == "python":
        got = python_effects(code)
        if got is not None:
            return got
    strings = [strip_mode(s) for s in literals(code)]
    writes = []
    if WRITE_HINT.search(code):
        kind = DESTROY if DESTROY_HINT.search(code) else WRITE
        writes = [(s, kind) for s in strings if path_like(s)]
    return writes, [], strings
