"""
The `ai-paladin` command.

    ai-paladin                 start the router (config in ~/.config/ai-paladin,
                               logs in ~/.local/state/ai-paladin/logs)
    ai-paladin --demo          start it with the repo's config/ and logs/, as
                               ./run_demo.sh does
    ai-paladin --where         print which files are in force, and exit
    ai-paladin --port 8800     listen on another port
    ai-paladin uninstall       remove the Claude Code hook from every place it
                               was installed, THEN pip uninstall AI-Paladin.
                               Use this instead of a plain pip uninstall:
                               pip cannot run anything at uninstall time, so
                               it cannot remove the hook or warn you.

Also runnable without installing: `python3 -m ai_paladin` from ai-paladin/.

The folders are chosen here, in the environment, BEFORE any other ai_paladin
module is imported - ai_paladin.paths reads them once, at import.
"""

import argparse
import os
import sys

from ai_paladin import __version__


def _parse(argv):
    ap = argparse.ArgumentParser(
        prog="ai-paladin",
        description="ℂacheℝefresh's AI-Paladin router: keeps protected work "
                    "on-prem, enforced by the router rather than by a prompt.",
        epilog="To remove AI-Paladin: 'ai-paladin uninstall [--yes]'. It "
               "removes the Claude Code hook from every place it was "
               "installed, then runs pip uninstall. Do not use a plain pip "
               "uninstall while the hook is installed.")
    ap.add_argument("--demo", action="store_true",
                    help="use the repo's config/ and logs/ folders "
                         "(the demo overlay and in-repo audit logs)")
    ap.add_argument("--port", type=int,
                    help="port to listen on (default 8722, or $PALADIN_PORT)")
    ap.add_argument("--where", action="store_true",
                    help="show the config and log folders and every file in "
                         "force, then exit")
    ap.add_argument("--version", action="version",
                    version="ai-paladin " + __version__)
    return ap.parse_args(argv)


def _shipped_missing() -> list:
    from ai_paladin import config_layers, paths
    return [paths.shipped(*rel) for rel in config_layers.SHIPPED_FILES.values()
            if not os.path.isfile(paths.shipped(*rel))]


def _where() -> int:
    from ai_paladin import config_layers, paths
    print("config folder  %s" % paths.CONFIG_DIR)
    print("log folder     %s" % paths.LOG_DIR)
    print("shipped files  %s" % paths.BASE)
    kw, rep = config_layers.load_keywords()
    for s in rep["sources"]:
        print("  %-21s %-12s %s  %s"
              % (s["file"], s["source"], s["sha256"], s["path"]))
    for name in config_layers.REPLACED_WHOLE:
        path, source = config_layers.resolve(name)
        print("  %-21s %-12s %s  %s"
              % (name, source, config_layers.sha256_short(path), path))
    n = sum(len(g.get("terms", [])) for g in kw.get("protected_terms", []))
    print("protected      %d terms in %d groups, %d paths"
          % (n, len(kw.get("protected_terms", [])),
             len(kw.get("protected_paths", []))))
    for w in rep["weakened"]:
        print("  WEAKENED     %s" % w)
    for note in rep["notes"]:
        print("  note         %s" % note)
    return 0


BANNER = "=" * 72


def _banner(*lines):
    print("\n" + BANNER)
    for line in lines:
        print("  " + line)
    print(BANNER)


def remover_command() -> list:
    """How this copy of AI-Paladin was installed decides how it is removed:
    pipx keeps its own records, so a pipx install is removed with pipx."""
    import shutil
    if "/pipx/venvs/" in sys.prefix.replace(os.sep, "/") and shutil.which("pipx"):
        return ["pipx", "uninstall", "ai-paladin"]
    return [sys.executable, "-m", "pip", "uninstall", "-y", "ai-paladin"]


def uninstall(argv) -> int:
    """`ai-paladin uninstall [--yes]`: hook first, package second."""
    import importlib.metadata
    import subprocess
    from ai_paladin import hook

    yes = "--yes" in argv or "-y" in argv
    places = hook.where_installed()
    try:
        version = importlib.metadata.version("ai-paladin")
    except importlib.metadata.PackageNotFoundError:
        version = None

    print("The Claude Code hook is installed in:")
    print("  " + ("\n  ".join(places) if places else "(nowhere AI-Paladin knows of)"))
    print("AI-Paladin package: %s" % ("ai-paladin %s (pip)" % version if version
                                      else "not installed with pip - nothing to remove"))
    if not yes:
        try:
            answer = input("\nRemove the hook from every place above%s? [y/N] "
                           % (" and uninstall AI-Paladin" if version else ""))
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing changed.")
            return 1

    removed, failed = hook.uninstall_all()
    for p in removed:
        print("hook removed from %s" % p)
    if failed:
        for p, err in failed:
            print("cannot read %s: %s" % (p, err), file=sys.stderr)
        _banner("STOPPED. AI-PALADIN WAS NOT UNINSTALLED.",
                "THE CLAUDE CODE HOOK COULD NOT BE REMOVED FROM THE FILE(S) ABOVE.",
                "FIX OR DELETE THE pre_tool_use.py ENTRY IN THEM BY HAND, THEN",
                "RUN 'ai-paladin uninstall' AGAIN. UNINSTALLING NOW WOULD MAKE",
                "CLAUDE CODE REFUSE EVERY TOOL CALL IN THOSE PROJECTS.")
        return 1

    pip_ok = True
    if version:
        sys.stdout.flush()              # our lines first, then pip's
        r = subprocess.run(remover_command())
        pip_ok = r.returncode == 0

    lines = ["AI-PALADIN'S CLAUDE CODE HOOK HAS BEEN REMOVED FROM %d PLACE%s."
             % (len(removed), "" if len(removed) == 1 else "S")]
    if version and pip_ok:
        lines.append("AI-PALADIN %s HAS BEEN UNINSTALLED." % version)
    elif version:
        lines += ["PIP COULD NOT UNINSTALL AI-PALADIN - SEE THE MESSAGE ABOVE.",
                  "THE HOOK IS ALREADY GONE, SO CLAUDE CODE IS SAFE TO USE."]
        lines.append("REMOVE THE PACKAGE THE WAY YOU INSTALLED IT - THE MESSAGE "
                     "ABOVE SAYS HOW.")
    lines += ["CLAUDE CODE WORKS NORMALLY IN NEW SESSIONS.",
              "KEPT: YOUR SETTINGS (~/.config/ai-paladin) AND AUDIT LOGS",
              "(~/.local/state/ai-paladin). DELETE THEM YOURSELF IF YOU WISH."]
    _banner(*lines)
    return 0 if pip_ok else 1


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["uninstall"]:
        return uninstall(argv[1:])
    args = _parse(argv)

    if args.demo:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not os.path.isfile(os.path.join(here, "config", "keywords.yaml")):
            print("ai-paladin: --demo needs a source checkout (it uses the "
                  "repo's config/ and logs/); this copy is installed from a "
                  "wheel.", file=sys.stderr)
            return 2
        os.environ["AI_PALADIN_CONFIG_DIR"] = os.path.join(here, "config")
        os.environ["AI_PALADIN_LOG_DIR"] = os.path.join(here, "logs")
    if args.port:
        os.environ["PALADIN_PORT"] = str(args.port)

    missing = _shipped_missing()
    if missing:
        print("ai-paladin: shipped defaults not found:\n  "
              + "\n  ".join(missing)
              + "\nThis installation is incomplete; reinstall the package "
                "(pip install --force-reinstall ai-paladin) or run from a "
                "source checkout.",
              file=sys.stderr)
        return 2

    from ai_paladin.config_layers import OverlayError
    try:
        if args.where:
            return _where()
        from ai_paladin.server import app
    except OverlayError as exc:
        print("ai-paladin: refusing to start - your keywords overlay cannot be "
              "applied:\n  %s" % exc, file=sys.stderr)
        return 2
    app.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
