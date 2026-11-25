"""
The `ai-paladin` command.

    ai-paladin                 start the router (config in ~/.config/ai-paladin,
                               logs in ~/.local/state/ai-paladin/logs)
    ai-paladin --demo          start it with the repo's config/ and logs/, as
                               ./run_demo.sh does
    ai-paladin --where         print which files are in force, and exit
    ai-paladin --port 8800     listen on another port

Also runnable without installing: `python3 -m ai_paladin` from ai-org-router/.

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
                    "on-prem, enforced by the router rather than by a prompt.")
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


def main(argv=None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)

    if args.demo:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        os.environ["AI_PALADIN_CONFIG_DIR"] = os.path.join(here, "config")
        os.environ["AI_PALADIN_LOG_DIR"] = os.path.join(here, "logs")
    if args.port:
        os.environ["PALADIN_PORT"] = str(args.port)

    missing = _shipped_missing()
    if missing:
        print("ai-paladin: shipped defaults not found:\n  "
              + "\n  ".join(missing)
              + "\nOnly a source checkout or an editable install "
                "(pip install -e) is supported until packaging is finished.",
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
