"""
The `ai-paladin` command.

    ai-paladin                 start the router (config in ~/.config/ai-paladin,
                               logs in ~/.local/state/ai-paladin/logs)
    ai-paladin --demo          start it with the repo's config/ and logs/, as
                               ./run_demo.sh does
    ai-paladin --where         print which files are in force, and exit
    ai-paladin --port 8800     listen on another port
    ai-paladin uninstall       run this FIRST, then `pip uninstall ai-paladin`.
                               Removes the hooks AI-Paladin added outside
                               Python (Claude Code settings entries), and only
                               those: it asks first, lists each one, keeps
                               hooks that were there before install or were
                               added by others since, and flags any of ours
                               that were edited. pip cannot run anything at
                               uninstall time, so it cannot do this for you.
                               Options: --yes, --dry-run, --remove-modified.

Also runnable without installing: `python3 -m ai_paladin` from ai-paladin/.

The folders are chosen here, in the environment, BEFORE any other ai_paladin
module is imported - ai_paladin.paths reads them once, at import.
"""

import argparse
import os
import sys

from ai_paladin import __version__, installs


def _parse(argv):
    ap = argparse.ArgumentParser(
        prog="ai-paladin",
        description="ℂacheℝefresh's AI-Paladin router: keeps protected work "
                    "on-prem, enforced by the router rather than by a prompt.",
        epilog="To remove AI-Paladin: run 'ai-paladin uninstall' first (it "
               "removes the hooks AI-Paladin added outside Python, and only "
               "those), then 'pip uninstall ai-paladin'. A plain pip "
               "uninstall leaves the hooks behind.")
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


def remover_hint() -> str:
    """The command to tell the person to run next, as they would type it."""
    return ("pipx uninstall ai-paladin" if remover_command()[0] == "pipx"
            else "pip uninstall ai-paladin")


# Rob's wording. It is the prompt, character for character.
PROMPT = "Do you want me to remove the hooks I added outside of python?(Y/n)"


def _ask(prompt: str, default_yes: bool):
    """True / False for an answer, None when there is no one to answer
    (input closed). Anything unclear asks again."""
    while True:
        try:
            answer = input(prompt + " ").strip().lower()
        except EOFError:
            return None
        if not answer:
            return default_yes
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def _list_plan(items, manifest_file) -> None:
    if any(installs.has_work(it) for it in items):
        print("AI-Paladin added these hooks outside of Python "
              "(recorded at install in %s):" % manifest_file)
    else:
        print("AI-Paladin has no hook of its own to remove (record: %s)."
              % manifest_file)
    for it in items:
        for fp, summ in it["remove"]:
            tag = ("sha256 %s" % installs.short(fp) if not it["legacy"]
                   else "recorded by an earlier version, matched by command")
            print("\n  REMOVE   %s\n           %s   [%s]" % (it["file"], summ, tag))
        for rec_fp, now_fp, summ in it["modified"]:
            print("\n  MODIFIED %s\n           %s\n           changed since "
                  "install: recorded sha256 %s, now %s. It will be KEPT unless "
                  "you say otherwise below."
                  % (it["file"], summ, installs.short(rec_fp),
                     installs.short(now_fp)))
    kept = [(it["file"], k) for it in items for k in it["kept"]]
    if kept:
        print("\nWas already present before install, keeping:")
        for f, k in kept:
            print("  %s\n           %s" % (f, k))
    gone = [it["file"] for it in items if it["gone"] or
            (not it["exists"] and not it["legacy"])]
    if gone:
        print("\nRecorded, but already gone (nothing to do): " + ", ".join(gone))
    print("\nEverything else in those files - other tools' hooks, and hooks "
          "added after install - is left exactly as it is.\n")


def uninstall(argv) -> int:
    """`ai-paladin uninstall [--yes] [--dry-run] [--remove-modified]`.

    Run BEFORE `pip uninstall ai-paladin`: pip cannot run code, so it cannot
    remove what AI-Paladin put outside Python. This removes exactly what the
    install manifest says we added, and then tells the person to run pip."""
    known = {"--yes", "-y", "--dry-run", "--remove-modified"}
    bad = [a for a in argv if a not in known]
    if bad:
        print("ai-paladin uninstall: unknown option %s\n"
              "usage: ai-paladin uninstall [--yes] [--dry-run] "
              "[--remove-modified]" % bad[0], file=sys.stderr)
        return 2
    yes = "--yes" in argv or "-y" in argv
    dry = "--dry-run" in argv
    force_mod = "--remove-modified" in argv

    try:
        items = installs.plan()
    except installs.ManifestError as exc:
        print("ai-paladin uninstall: %s\nNothing was removed. Fix or delete "
              "that file, or remove the pre_tool_use.py entry under "
              "hooks.PreToolUse in your Claude Code settings by hand, then "
              "run this again." % exc, file=sys.stderr)
        return 1
    unreadable = [it for it in items if it["error"]]
    if unreadable:
        for it in unreadable:
            print("cannot read %s: %s" % (it["file"], it["error"]), file=sys.stderr)
        _banner("STOPPED. NOTHING WAS REMOVED.",
                "A SETTINGS FILE ABOVE CANNOT BE READ. FIX OR REMOVE ITS",
                "pre_tool_use.py ENTRY BY HAND, THEN RUN 'ai-paladin uninstall' AGAIN.",
                "DO NOT RUN pip uninstall YET: CLAUDE CODE WOULD THEN REFUSE",
                "EVERY TOOL CALL IN THOSE PROJECTS.")
        return 1

    if any(installs.has_work(it) or it["kept"] or it["gone"] for it in items):
        _list_plan(items, installs.manifest_path())
    work = [it for it in items if installs.has_work(it)]

    if dry:
        print("Dry run: nothing was changed.")
        return 0

    removing = bool(work)
    include_modified = {}
    if work:
        if yes:
            answer = True
        else:
            answer = _ask(PROMPT, default_yes=True)
            if answer is None:
                print("No answer (input is closed). Nothing changed. Run "
                      "'ai-paladin uninstall --yes' to skip the question.")
                return 1
        if not answer:
            print("Nothing changed. The hooks stay. If you pip uninstall now, "
                  "Claude Code will refuse every tool call until they are "
                  "removed.")
            return 1
        for it in work:
            if not it["modified"]:
                continue
            if force_mod:
                include_modified[it["file"]] = True
            elif not yes:
                for _, _, summ in it["modified"]:
                    include_modified[it["file"]] = _ask(
                        "This entry in %s changed after install:\n  %s\n"
                        "Remove it anyway?(y/N)" % (it["file"], summ),
                        default_yes=False) is True

    removed, kept_modified, failed = [], [], []
    for it in items:
        inc = include_modified.get(it["file"], False)
        try:
            installs.remove(it, include_modified=inc)
        except (OSError, ValueError) as exc:
            failed.append((it["file"], str(exc)))
            continue
        if it["remove"] or (inc and it["modified"]):
            removed.append(it["file"])
        if it["modified"] and not inc:
            kept_modified += [(it["file"], s) for _, _, s in it["modified"]]
    for p in removed:
        print("hook removed from %s" % p)
    for p, err in failed:
        print("could not change %s: %s" % (p, err), file=sys.stderr)
    for p, summ in kept_modified:
        print("kept (edited after install): %s\n  %s" % (p, summ))

    if failed:
        _banner("STOPPED. SOME HOOK ENTRIES WERE NOT REMOVED (SEE ABOVE).",
                "FIX THE FILE(S), THEN RUN 'ai-paladin uninstall' AGAIN BEFORE",
                "YOU RUN pip uninstall, OR CLAUDE CODE WILL REFUSE EVERY TOOL CALL.")
        return 1
    lines = []
    if removing:
        lines.append("DONE. THE HOOKS AI-PALADIN ADDED WERE REMOVED FROM %d "
                     "FILE%s." % (len(removed), "" if len(removed) == 1 else "S"))
    else:
        lines.append("NO HOOK ADDED BY AI-PALADIN IS RECORDED, SO NONE WAS REMOVED.")
    if kept_modified:
        lines += ["KEPT, BECAUSE YOU EDITED THEM AFTER INSTALL: %d ENTRY(S) ABOVE."
                  % len(kept_modified),
                  "REMOVE THEM BY HAND BEFORE pip uninstall, OR CLAUDE CODE",
                  "REFUSES EVERY TOOL CALL (OR RERUN WITH --remove-modified)."]
    lines += ["NEXT, RUN:  %s" % remover_hint(),
              "KEPT: YOUR SETTINGS (~/.config/ai-paladin) AND AUDIT LOGS",
              "(~/.local/state/ai-paladin). DELETE THEM YOURSELF IF YOU WISH."]
    _banner(*lines)
    return 1 if kept_modified else 0


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
