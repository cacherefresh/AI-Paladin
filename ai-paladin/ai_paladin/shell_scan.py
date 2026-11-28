"""
What a Bash command runs, as far as a parser can tell without running it.

Used by the Claude Code PreToolUse hook (ai_paladin/hook.py). Matching the raw
command text against patterns misses commands that are wrapped in another
shell (`sh -c '...'`, `bash -c "..."`, `eval`, `$(...)`, backticks, a here-doc
fed to a shell). This module splits a command the way a POSIX shell would -
quotes removed, `;` `&&` `||` `|` `&` and newlines as separators, wrappers such
as sudo / env / timeout / xargs stripped - and hands back every command it
contains, including the ones nested inside another shell, so the hook can
apply the same rules to each.

LIMIT: this reads the command text; it does not run it. Anything decided only
at run time - a variable's value, an alias, a function, a string decoded from
base64 - is invisible to it. The hook is a hardened guardrail, not a sandbox
(docs/ROADMAP.md, section 9).
"""

import os
import re
import shlex
from typing import List, Optional

# Separators between commands, as shlex(punctuation_chars=True) emits them.
CONTROL = {";", "&&", "||", "|", "&", "|&", ";;", ";&", ";;&", "(", ")",
           "{", "}", "!"}
# Redirection operators. The word after one is a file (or, after >& / <&,
# possibly a file descriptor).
REDIRECT = {">", ">>", ">|", "&>", "&>>", "<", "<>", ">&", "<&", "<<<"}
# Shell keywords that may start a segment before the real command.
KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while",
            "until", "time", "coproc"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "busybox"}

# Wrappers that run the rest of the line as a command: name -> options that
# take a value.
_WRAPPERS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "-S", "--unset", "--chdir"},
    "nohup": set(), "exec": {"-a"}, "command": set(), "builtin": set(),
    "nice": {"-n", "--adjustment"}, "ionice": {"-c", "-n", "-p"},
    "stdbuf": {"-i", "-o", "-e"}, "setsid": set(), "chrt": set(),
    "time": {"-f", "-o"}, "unbuffer": set(),
    "xargs": {"-I", "-i", "-n", "-P", "-L", "-l", "-d", "-s", "-E", "-e",
              "-a", "--arg-file", "--delimiter", "--max-args",
              "--max-procs", "--replace"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
}
# Wrappers whose first positional argument is theirs, not the command's.
_WRAPPER_POSITIONAL = {"timeout": 1, "chrt": 1}

SUBST = "__AI_PALADIN_SUBST__"
MAX_SCRIPT_BYTES = 1 << 20


class Segment:
    """One simple command: its words (wrappers and assignments removed),
    its redirections, and the here-doc bodies fed to it."""

    def __init__(self, words, redirects, heredocs):
        self.words: List[str] = words
        self.redirects: List[tuple] = redirects      # (operator, word)
        self.heredocs: List[str] = heredocs

    @property
    def name(self) -> str:
        return os.path.basename(self.words[0]) if self.words else ""

    def __repr__(self):
        return "Segment(%r, %r)" % (self.words, self.redirects)


class Scan:
    """Everything one command string contains, before any nesting is
    followed: its segments, and the inner command strings it runs (each to
    be scanned in turn)."""

    def __init__(self):
        self.segments: List[Segment] = []
        self.inner: List[str] = []          # nested shell command strings

    @property
    def words(self) -> List[str]:
        return [w for s in self.segments for w in s.words]


# ---------------------------------------------------------------------------
# pass 1: pull out what the shell would run separately
# ---------------------------------------------------------------------------

def _matching_paren(text: str, i: int) -> int:
    """Index of the ')' closing the '(' at text[i], or len(text)."""
    depth, quote, n = 0, None, len(text)
    while i < n:
        c = text[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2
                continue
            if c == quote:
                quote = None
        elif c == "\\":
            i += 2
            continue
        elif c in "'\"":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def _prepare(command: str):
    """
    (text, substitutions, heredocs). Command and process substitutions
    ($(...), `...`, <(...), >(...)) are cut out and returned to be scanned on
    their own; here-doc bodies are cut out and returned in order; newlines
    outside quotes become ';'.
    """
    out, subs, docs = [], [], []
    pending = []                   # here-doc delimiters waiting for a newline
    quote, i, n = None, 0, len(command)
    while i < n:
        c = command[i]
        if quote == "'":
            out.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            if command[i + 1] == "\n" and quote is None:     # line continuation
                i += 2
                continue
            out.append(command[i:i + 2])
            i += 2
            continue
        if c in "$<>" and command[i + 1:i + 2] == "(" and not (
                c in "<>" and quote):
            end = _matching_paren(command, i + 1)
            inner = command[i + 2:end]
            if c == "$" and inner.startswith("(") and inner.endswith(")"):
                inner = inner[1:-1]                  # $(( arithmetic ))
            subs.append(inner)
            out.append(SUBST)
            i = end + 1
            continue
        if c == "`":
            end = command.find("`", i + 1)
            end = n if end < 0 else end
            subs.append(command[i + 1:end])
            out.append(SUBST)
            i = end + 1
            continue
        if quote == '"':
            out.append(c)
            if c == '"':
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "<" and command.startswith("<<", i) and \
                not command.startswith("<<<", i):
            m = re.match(r"<<(-?)\s*(['\"]?)([^\s'\";|&<>()]+)\2",
                         command[i:])
            if m:
                pending.append((m.group(3), bool(m.group(1))))
                out.append("<< " + m.group(3) + " ")
                i += m.end()
                continue
        if c == "\n":
            out.append(" ; ")
            i += 1
            for delim, strip_tabs in pending:
                body = []
                while i < n:
                    j = command.find("\n", i)
                    j = n if j < 0 else j
                    line = command[i:j]
                    i = j + 1
                    if (line.lstrip("\t") if strip_tabs else line) == delim:
                        break
                    body.append(line)
                docs.append("\n".join(body))
            pending = []
            continue
        out.append(c)
        i += 1
    return "".join(out), subs, docs


# ---------------------------------------------------------------------------
# pass 2: words and segments
# ---------------------------------------------------------------------------

def tokens(text: str) -> List[str]:
    """Shell words, quotes removed, operators as their own tokens."""
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""
        raw = list(lex)
    except ValueError:                  # unbalanced quote: bash would refuse
        raw = text.split()              # it too, but scan what is there
    out = []
    for t in raw:                       # shlex glues runs like ');' or '>&-'
        if t and set(t) <= _PUNCT and t not in _OPERATORS:
            out.extend(_split_operators(t))
        else:
            out.append(t)
    return out


_PUNCT = set("();<>|&")
_OPERATORS = sorted(CONTROL | REDIRECT | {"<<", "<<-"}, key=len, reverse=True)


def _split_operators(run: str) -> List[str]:
    out, i = [], 0
    while i < len(run):
        for op in _OPERATORS:
            if run.startswith(op, i):
                out.append(op)
                i += len(op)
                break
        else:
            out.append(run[i])
            i += 1
    return out


def _strip_wrappers(words: List[str]) -> List[str]:
    changed = True
    while words and changed:
        changed = False
        while words and (re.match(r"^[A-Za-z_]\w*=", words[0])
                         or words[0] in KEYWORDS):
            words = words[1:]
            changed = True
        if not words:
            break
        name = os.path.basename(words[0])
        if name in _WRAPPERS:
            takes = _WRAPPERS[name]
            i, positional = 1, _WRAPPER_POSITIONAL.get(name, 0)
            while i < len(words):
                w = words[i]
                if w == "--":
                    i += 1
                    break
                if w in takes:
                    i += 2
                    continue
                if w.startswith("-") and len(w) > 1:
                    i += 1
                    continue
                if name == "env" and re.match(r"^[A-Za-z_]\w*=", w):
                    i += 1
                    continue
                if positional:
                    positional -= 1
                    i += 1
                    continue
                break
            words = words[i:]
            changed = True
    return words


def _segments(toks: List[str], docs: List[str]) -> List[Segment]:
    segs, words, redirects, mine = [], [], [], []
    docs = list(docs)

    def flush():
        w = _strip_wrappers(words)
        if w or redirects:
            segs.append(Segment(w, list(redirects), list(mine)))

    i = 0
    while i < len(toks):
        t = toks[i]
        if t in CONTROL:
            flush()
            words, redirects, mine = [], [], []
            i += 1
            continue
        if t in REDIRECT or t == "<<" or t == "<<-":
            target = toks[i + 1] if i + 1 < len(toks) else ""
            if t in ("<<", "<<-"):
                if docs:
                    mine.append(docs.pop(0))
            else:
                redirects.append((t, target))
            i += 2
            continue
        if re.fullmatch(r"\d+", t) and i + 1 < len(toks) and \
                toks[i + 1] in REDIRECT:
            i += 1                       # the fd number of `2>file`
            continue
        words.append(t)
        i += 1
    flush()
    return segs


# ---------------------------------------------------------------------------
# nesting: commands that run other commands
# ---------------------------------------------------------------------------

def shell_c_argument(words: List[str]) -> Optional[str]:
    """The command string of `sh -c '...'` / `bash -lc "..."`, or None."""
    if not words or os.path.basename(words[0]) not in SHELLS:
        return None
    args = words[1:]
    if os.path.basename(words[0]) == "busybox" and args[:1] and \
            args[0] in SHELLS:
        args = args[1:]
    for k, a in enumerate(args):
        if a == "--":
            return None
        if a.startswith("-") and not a.startswith("--") and "c" in a[1:]:
            rest = [x for x in args[k + 1:]]
            while rest and rest[0].startswith("-") and rest[0] != "-":
                rest = rest[1:]          # sh -c -e 'cmd' ordering
            return rest[0] if rest else ""
        if not a.startswith("-"):
            return None
    return None


def _inner_commands(seg: Segment) -> List[str]:
    found = []
    w = seg.words
    if not w:
        return found
    inner = shell_c_argument(w)
    if inner is not None:
        found.append(inner)
    elif seg.name == "eval":
        found.append(" ".join(w[1:]))
    elif seg.name in SHELLS and seg.heredocs and not any(
            not a.startswith("-") for a in w[1:]):
        found.extend(seg.heredocs)        # bash <<EOF ... EOF
    elif seg.name in SHELLS:
        for op, target in seg.redirects:
            if op == "<<<":
                found.append(target)      # bash <<< 'cmd'
    return found


def scan(command: str) -> Scan:
    """Split one command string. Nested command strings are listed in
    `.inner`, not followed: the caller scans each, with a depth limit."""
    result = Scan()
    text, subs, docs = _prepare(str(command))
    result.inner.extend(subs)
    result.segments = _segments(tokens(text), docs)
    for seg in result.segments:
        result.inner.extend(_inner_commands(seg))
    return result
