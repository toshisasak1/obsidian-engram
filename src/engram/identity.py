"""Identity framework — template files for AI assistants.

Provides helpers to install and check the vault's identity files
(SOUL.md, USER.md, AGENTS.md, TOOLS.md).
"""

from __future__ import annotations

import shutil
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent.parent.parent / "vault_template"
IDENTITY_FILES = ["SOUL.md", "USER.md", "AGENTS.md", "TOOLS.md", "CLAUDE.md"]

# Directory structure for the shared knowledge base.
KB_DIRS = ["_kb", "_kb/decisions", "_kb/sessions", "_kb/templates"]
KB_FILES = {"_kb/index.md": TEMPLATE_DIR / "_kb" / "index.md"}


def install_identity_files(vault_path: Path, *, overwrite: bool = False) -> list[str]:
    """Copy identity template files to the vault root.

    Parameters
    ----------
    vault_path:
        Root directory of the Obsidian vault.
    overwrite:
        If ``True``, replace existing files. Otherwise skip them.

    Returns
    -------
    list[str]
        Filenames that were actually created (not skipped).
    """
    created: list[str] = []
    for filename in IDENTITY_FILES:
        src = TEMPLATE_DIR / filename
        dst = vault_path / filename
        if dst.exists() and not overwrite:
            continue
        if src.exists():
            shutil.copy2(src, dst)
            created.append(filename)
    return created


def install_kb_structure(vault_path: Path, *, overwrite: bool = False) -> list[str]:
    """Create the ``_kb/`` knowledge base directories and seed files.

    Parameters
    ----------
    vault_path:
        Root directory of the Obsidian vault.
    overwrite:
        If ``True``, replace the seed ``index.md``. Directories are always
        created regardless of this flag.

    Returns
    -------
    list[str]
        Relative paths that were actually created.
    """
    created: list[str] = []
    for dirname in KB_DIRS:
        dirpath = vault_path / dirname
        if not dirpath.exists():
            dirpath.mkdir(parents=True, exist_ok=True)
            created.append(f"{dirname}/")

    for relpath, src in KB_FILES.items():
        dst = vault_path / relpath
        if dst.exists() and not overwrite:
            continue
        if src.exists():
            shutil.copy2(src, dst)
            created.append(relpath)

    return created


def check_identity_files(vault_path: Path) -> dict[str, bool]:
    """Check which identity files exist in the vault.

    Returns
    -------
    dict[str, bool]
        Mapping of filename to existence flag.
    """
    return {f: (vault_path / f).exists() for f in IDENTITY_FILES}
