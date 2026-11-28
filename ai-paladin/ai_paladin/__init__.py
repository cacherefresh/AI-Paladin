"""AI-Paladin. Installed as `ai-paladin`; imported as `ai_paladin` because
Python import names cannot contain a hyphen."""

from pathlib import Path


def _read_version() -> str:
    """The version in the repo-root VERSION file, or the installed package metadata.

    VERSION at the repository root is the single source. setuptools reads
    the same file for the wheel. When that file is not next to a checkout
    (a pip install of the wheel), the version recorded in the package
    metadata is used instead.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "VERSION"
        if candidate.is_file() and (parent / "pyproject.toml").is_file():
            line = candidate.read_text(encoding="utf-8").strip().splitlines()
            if line:
                return line[0].strip()
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version("ai-paladin")
    except PackageNotFoundError:
        return "0.0.0+unknown"


__version__ = _read_version()
