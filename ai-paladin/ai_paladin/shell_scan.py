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

import glob
import os
import re
import shlex
from typing import Dict, List, Optional

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

    def __init__(self, words, redirects, heredocs, assigns=None):
        self.words: List[str] = words
        self.assigns: Dict[str, str] = assigns or {}  # VAR=value on the line
        self.redirects: List[tuple] = redirects      # (operator, word)
        self.heredocs: List[str] = heredocs
        self.inner: List[str] = []           # command strings it runs

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
        self.substitutions: List[str] = []  # $(...), `...`, <(...)

    @property
    def inner(self) -> List[str]:
        """Every nested command string: substitutions, then each segment's."""
        return self.substitutions + [c for s in self.segments for c in s.inner]

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


def _strip_wrappers(words: List[str], assigns: Dict[str, str] = None):
    assigns = {} if assigns is None else assigns
    changed = True
    while words and changed:
        changed = False
        while words and (re.match(r"^[A-Za-z_]\w*=", words[0])
                         or words[0] in KEYWORDS):
            if "=" in words[0]:
                k, v = words[0].split("=", 1)
                assigns[k] = v
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
                    k, v = w.split("=", 1)
                    assigns[k] = v
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
        assigns = {}
        w = _strip_wrappers(words, assigns)
        if w or redirects or assigns:
            segs.append(Segment(w, list(redirects), list(mine), assigns))

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
# what a word names, once the shell has expanded it
# ---------------------------------------------------------------------------

_VAR = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))")


def expand_word(word: str, env: Dict[str, str], cwd: str) -> List[str]:
    """
    The path(s) a word names after the shell expands it: ~ and $VAR /
    ${VAR} (from `env`; unknown variables are left as written), then globs
    against what exists on disk. A glob that matches nothing stays as the
    pattern, as in bash.
    """
    w = str(word)
    if w == "~" or w.startswith("~/"):
        w = (env.get("HOME") or os.path.expanduser("~")) + w[1:]
    w = _VAR.sub(lambda m: env.get(m.group(1) or m.group(2), m.group(0)), w)
    if any(c in w for c in "*?["):
        pattern = w if os.path.isabs(w) else os.path.join(cwd, w)
        try:
            hits = sorted(glob.glob(pattern))[:500]
        except (OSError, re.error):
            hits = []
        if hits:
            return hits
        # Nothing matches the whole word (a file not created yet): resolve
        # the folder part, so `> /e*c/new` is judged as `/etc/new`.
        head, tail = os.path.split(pattern)
        if any(c in head for c in "*?["):
            try:
                dirs = sorted(glob.glob(head))[:500]
            except (OSError, re.error):
                dirs = []
            if dirs:
                return [os.path.join(d, tail) for d in dirs]
    return [w]


def word_paths(word: str, env: Dict[str, str], cwd: str) -> List[str]:
    """expand_word, also for the value of `--opt=value` / `of=value`."""
    out = expand_word(word, env, cwd)
    m = re.match(r"^-{0,2}[A-Za-z][\w-]*=(.+)$", word)
    if m:
        out += expand_word(m.group(1), env, cwd)
    return out


# ---------------------------------------------------------------------------
# files a command writes
# ---------------------------------------------------------------------------

WRITE, DESTROY = "write", "destroy"
_FILE_REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<>"}


def _operands(args: List[str], takes: set):
    """(operands, {option: [values]}) for one command's arguments. `takes`
    are the options that consume a value (`-t DIR`, `-tDIR`, `--opt=V`)."""
    ops, vals, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            ops.extend(args[i + 1:])
            break
        if a.startswith("--") and "=" in a:
            k, v = a.split("=", 1)
            vals.setdefault(k, []).append(v)
        elif a in takes:
            vals.setdefault(a, []).append(args[i + 1] if i + 1 < len(args)
                                          else "")
            i += 1
        elif a.startswith("-") and not a.startswith("--") and len(a) > 2 \
                and a[:2] in takes:
            vals.setdefault(a[:2], []).append(a[2:])
        elif a.startswith("-") and a != "-":
            vals.setdefault(a, []).append("")
        else:
            ops.append(a)
        i += 1
    return ops, vals


def _short_flag(vals: dict, letter: str, long: str = None) -> bool:
    return any((k.startswith("-") and not k.startswith("--") and letter in k)
               or (long and k.startswith(long)) for k in vals)


_DESTROY_ALL = {"rm", "rmdir", "unlink", "shred", "srm"}
_WRITE_ALL = {"touch": {"-d", "-t", "-r", "--date", "--reference"},
              "mkdir": {"-m", "--mode"}, "truncate": {"-s", "-r", "--size",
                                                     "--reference"},
              "tee": set(), "mkfifo": {"-m", "--mode"}}
_COPY_LIKE = {"cp": {"-t", "-S", "--target-directory", "--suffix"},
              "install": {"-t", "-m", "-o", "-g", "-S", "--mode", "--owner",
                          "--group", "--target-directory", "--suffix"},
              "ln": {"-t", "-S", "--target-directory", "--suffix"},
              "link": set(), "scp": {"-P", "-i", "-o", "-F", "-c", "-l"},
              "rsync": {"-e", "--rsh", "-f", "--filter", "--exclude",
                        "--include", "-T", "--temp-dir"}}
_MODE = re.compile(r"^[-+=][rwxXstugo,+=-]*$")


def write_targets(seg: Segment) -> List[tuple]:
    """[(word, WRITE or DESTROY)] - the files this one command writes,
    renames or deletes, as written (not yet expanded). Covers redirections
    and the common file utilities; a program that writes files on its own
    terms is not visible here."""
    out = []
    for op, t in seg.redirects:
        if op in _FILE_REDIRECTS or (op == ">&" and
                                     not re.fullmatch(r"\d*-?", t)):
            out.append((t, WRITE))
    if not seg.words:
        return out
    name, args = seg.name, seg.words[1:]
    if name in _DESTROY_ALL:
        ops, _ = _operands(args, set())
        out += [(o, DESTROY) for o in ops]
    elif name in _WRITE_ALL:
        ops, _ = _operands(args, _WRITE_ALL[name])
        out += [(o, WRITE) for o in ops]
    elif name == "mv":
        ops, vals = _operands(args, {"-t", "-S", "--target-directory",
                                     "--suffix"})
        out += [(o, DESTROY) for o in ops]
        out += [(v, WRITE) for k in ("-t", "--target-directory")
                for v in vals.get(k, [])]
    elif name in _COPY_LIKE:
        ops, vals = _operands(args, _COPY_LIKE[name])
        tdir = [v for k in ("-t", "--target-directory") for v in vals.get(k, [])]
        if tdir:
            out += [(v, WRITE) for v in tdir]
        elif name == "install" and "-d" in vals:
            out += [(o, WRITE) for o in ops]
        elif len(ops) >= 2:
            out.append((ops[-1], WRITE))
    elif name in ("chmod", "chown", "chgrp", "chattr", "setfacl"):
        mode_dash = [a for a in args if _MODE.match(a) and
                     a not in ("-R", "-f", "-v", "-c", "-h", "-H", "-L", "-P")]
        ops, vals = _operands([a for a in args if a not in mode_dash],
                              {"--reference"})
        files = ops if (mode_dash or "--reference" in vals) else ops[1:]
        out += [(o, WRITE) for o in files]
    elif name == "dd":
        out += [(a[3:], WRITE) for a in args if a.startswith("of=")]
    elif name in ("sed", "gsed", "perl"):
        takes = {"-e", "-f", "--expression", "--file"} if name != "perl" \
            else {"-e", "-E", "-M", "-I", "-x"}
        ops, vals = _operands(args, takes)
        if _short_flag(vals, "i", "--in-place"):
            has_script = any(k in vals for k in ("-e", "-f", "-E",
                                                 "--expression", "--file"))
            out += [(o, WRITE) for o in (ops if has_script else ops[1:])]
    elif name in ("curl", "wget"):
        takes = ({"-o", "--output", "--output-dir", "-K", "--config", "-d",
                  "-H", "-u", "-X", "-A", "-e", "-b", "-c", "-F", "-T"}
                 if name == "curl" else
                 {"-O", "--output-document", "-P", "--directory-prefix",
                  "-o", "-a", "--output-file", "--append-output"})
        _, vals = _operands(args, takes)
        for k in ("-o", "--output", "--output-dir", "-c", "-O",
                  "--output-document", "-P", "--directory-prefix", "-a",
                  "--output-file", "--append-output"):
            if name == "curl" and k in ("-O", "-P", "-a"):
                continue
            out += [(v, WRITE) for v in vals.get(k, []) if v and v != "-"]
    elif name in ("tar", "bsdtar", "unzip"):
        if name == "unzip":
            _, vals = _operands(args, {"-d", "-x"})
            out += [(v, WRITE) for v in vals.get("-d", [])]
        else:
            first = args[0] if args else ""
            _, vals = _operands(args, {"-C", "--directory", "-f", "--file",
                                       "-T", "-X"})
            extracting = (re.fullmatch(r"[A-Za-z]*x[A-Za-z]*", first)
                          or _short_flag(vals, "x", "--extract"))
            if extracting:
                out += [(v, WRITE) for k in ("-C", "--directory")
                        for v in vals.get(k, [])]
    elif name == "find":
        if "-delete" in args or any(
                a in ("-exec", "-execdir", "-ok", "-okdir") and
                k + 1 < len(args) and os.path.basename(args[k + 1]) in
                (_DESTROY_ALL | {"mv"}) for k, a in enumerate(args)):
            starts = []
            for a in args:
                if a.startswith(("-", "(", "!")):
                    break
                starts.append(a)
            out += [(s, DESTROY) for s in (starts or ["."])]
    return out


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


# ---------------------------------------------------------------------------
# interpreters and scripts: code the command runs
# ---------------------------------------------------------------------------

_INTERP = [(re.compile(r"^(python|pypy)[\d.]*$"), "python", {"-c"},
            {"-W", "-X", "-Q"}),
           (re.compile(r"^perl[\d.]*$"), "perl", {"-e", "-E"},
            {"-M", "-I", "-x", "-l", "-0"}),
           (re.compile(r"^ruby[\d.]*$"), "ruby", {"-e"}, {"-r", "-I", "-C"}),
           (re.compile(r"^(node|nodejs|bun)$"), "node",
            {"-e", "--eval", "-p", "--print"}, {"-r", "--require"}),
           (re.compile(r"^php[\d.]*$"), "php", {"-r"}, {"-d", "-c"}),
           (re.compile(r"^(osascript|lua[\d.]*|tclsh|Rscript)$"), "other",
            {"-e"}, set())]


def _read_script(path: str, env: Dict[str, str], cwd: str) -> Optional[str]:
    p = expand_word(path, env, cwd)[0]
    p = p if os.path.isabs(p) else os.path.join(cwd, p)
    try:
        if not os.path.isfile(p) or os.path.getsize(p) > MAX_SCRIPT_BYTES:
            return None
        with open(p, "rb") as fh:
            data = fh.read(MAX_SCRIPT_BYTES)
    except OSError:
        return None
    if b"\0" in data[:4096]:
        return None                          # a binary, not a script
    return data.decode("utf-8", "replace")


def _lang_of(text: str) -> str:
    first = text.split("\n", 1)[0]
    if not first.startswith("#!"):
        return "shell"                       # no shebang: sh runs it
    for rx, lang, _, _ in _INTERP:
        for word in re.split(r"[\s/]+", first[2:]):
            if rx.match(word):
                return lang
    return "shell"


def programs(seg: Segment, env: Dict[str, str], cwd: str) -> List[tuple]:
    """
    [(language, source)] for code this command hands to an interpreter:
    `python3 -c CODE`, `perl -e CODE`, `node -e CODE`, a script file run by
    an interpreter, a shell, `source` or by its own path (./x.sh), and a
    here-doc / here-string / `< file` fed to an interpreter. Language is
    "shell", "python", "perl", "ruby", "node", "php" or "other". Script files
    are read from disk at the moment the hook runs.
    """
    out = []
    w = seg.words
    if not w:
        return out
    name, args = seg.name, w[1:]

    def stdin_sources(lang):
        for doc in seg.heredocs:
            out.append((lang, doc))
        for op, target in seg.redirects:
            if op == "<<<":
                out.append((lang, target))
            elif op == "<":
                text = _read_script(target, env, cwd)
                if text is not None:
                    out.append((lang, text))

    for rx, lang, code_flags, takes in _INTERP:
        if not rx.match(name):
            continue
        i = 0
        while i < len(args):
            a = args[i]
            if a in code_flags:
                if i + 1 < len(args):
                    out.append((lang, args[i + 1]))
                return out
            hit = next((f for f in code_flags
                        if len(f) == 2 and a.startswith(f) and len(a) > 2
                        and not a.startswith("--")), None)
            if hit:                              # -c'code' / -pe'code'
                out.append((lang, a[2:]))
                return out
            if lang == "perl" and re.fullmatch(r"-[a-zA-Z]*[eE]", a):
                if i + 1 < len(args):            # perl -pie 'code'
                    out.append((lang, args[i + 1]))
                return out
            if lang == "python" and a == "-m":
                return out                       # a module, not a file
            if a in takes:
                i += 2
                continue
            if a == "-":
                break
            if a.startswith("-"):
                i += 1
                continue
            text = _read_script(a, env, cwd)
            if text is not None:
                out.append((lang, text))
            return out
        stdin_sources(lang)
        return out

    if name in SHELLS and shell_c_argument(w) is None:
        ops = [a for a in args if not a.startswith("-")]
        if ops:
            text = _read_script(ops[0], env, cwd)
            if text is not None:
                out.append(("shell", text))
        else:
            for op, target in seg.redirects:
                if op == "<":
                    text = _read_script(target, env, cwd)
                    if text is not None:
                        out.append(("shell", text))
    elif name in ("source", ".") and args:
        text = _read_script(args[0], env, cwd)
        if text is not None:
            out.append(("shell", text))
    elif "/" in w[0]:                            # ./build.sh, /tmp/x/run
        text = _read_script(w[0], env, cwd)
        if text is not None:
            out.append((_lang_of(text), text))
    return out


def scan(command: str) -> Scan:
    """Split one command string. Nested command strings are listed (in
    `.substitutions` and each segment's `.inner`), not followed: the caller
    scans each, with a depth limit."""
    result = Scan()
    text, subs, docs = _prepare(str(command))
    result.substitutions.extend(subs)
    result.segments = _segments(tokens(text), docs)
    for seg in result.segments:
        seg.inner.extend(_inner_commands(seg))
    return result
