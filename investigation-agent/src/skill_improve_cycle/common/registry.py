"""Local skill registry: numbered revisions, one active pointer, activation and rollback."""

import difflib
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from skill_improve_cycle.common.paths import PROJECT_ROOT

SKILL = "investigate-incident"
SCRIPT = Path(SKILL) / "scripts" / "investigate.py"
_REVISION = re.compile(r"^r[1-9]\d*$")


class RegistryError(ValueError):
    """A registry operation that must not proceed."""


def registry_root(root=None):
    return Path(root or os.getenv("SKILL_REGISTRY_ROOT") or PROJECT_ROOT / "skill-registry").resolve()


def revision_dir(revision, root=None):
    """Directory that contains the skill folder of one revision."""
    if not _REVISION.match(revision or ""):
        raise RegistryError(f"Invalid revision name: {revision!r}")
    path = registry_root(root) / "revisions" / revision
    if not (path / SKILL / "SKILL.md").is_file():
        raise RegistryError(f"Revision {revision} does not exist in {registry_root(root)}")
    return path


def active_revision(root=None):
    pointer = registry_root(root) / "active"
    if not pointer.is_file():
        raise RegistryError(f"No active revision in {registry_root(root)}")
    revision = pointer.read_text().strip()
    revision_dir(revision, root)
    return revision


def list_revisions(root=None):
    base = registry_root(root) / "revisions"
    names = [p.name for p in base.iterdir() if _REVISION.match(p.name)] if base.is_dir() else []
    return sorted(names, key=lambda name: int(name[1:]))


def read_meta(revision, root=None):
    return json.loads((revision_dir(revision, root) / "revision.json").read_text())


def write_meta(revision, meta, root=None):
    (revision_dir(revision, root) / "revision.json").write_text(json.dumps(meta, indent=2) + "\n")


def read_script(revision, root=None):
    return (revision_dir(revision, root) / SCRIPT).read_text()


def create_candidate(program, *, base, reason, failure_id, source_traces, checks, verification, root=None):
    """Copy the base revision, replace its program and store it as a candidate."""
    source = revision_dir(base, root)
    existing = list_revisions(root)
    revision = f"r{int(existing[-1][1:]) + 1}"
    target = registry_root(root) / "revisions" / revision
    shutil.copytree(source / SKILL, target / SKILL)
    (target / SCRIPT).write_text(program if program.endswith("\n") else program + "\n")
    write_meta(revision, {
        "revision": revision,
        "status": "candidate",
        "base_revision": base,
        "created_at": datetime.now(UTC).isoformat(),
        "reason": reason,
        "failure_id": failure_id,
        "source_traces": source_traces,
        "checks": checks,
        "verification": verification,
    }, root)
    return revision


def diff(revision, against=None, root=None):
    """Unified diff of every skill file between two revisions (default: the base)."""
    against = against or read_meta(revision, root).get("base_revision") or active_revision(root)
    old, new = revision_dir(against, root) / SKILL, revision_dir(revision, root) / SKILL
    names = sorted({str(p.relative_to(d)) for d in (old, new) for p in d.rglob("*") if p.is_file()})
    chunks = []
    for name in names:
        before = (old / name).read_text().splitlines(keepends=True) if (old / name).is_file() else []
        after = (new / name).read_text().splitlines(keepends=True) if (new / name).is_file() else []
        chunks.extend(difflib.unified_diff(before, after, f"{against}/{name}", f"{revision}/{name}"))
    return "".join(chunks)


def activate(revision, root=None):
    """Make a checked and verified candidate the active revision."""
    meta = read_meta(revision, root)
    if meta.get("status") != "candidate":
        raise RegistryError(f"{revision} is {meta.get('status')}, not a candidate")
    if not meta.get("checks", {}).get("passed"):
        raise RegistryError(f"{revision} did not pass the static checks: {meta.get('checks', {}).get('problems')}")
    if meta.get("verification", {}).get("complete") is not True:
        raise RegistryError(f"{revision} has no verified execution")
    previous = active_revision(root)
    previous_meta = read_meta(previous, root)
    previous_meta["status"] = "superseded"
    write_meta(previous, previous_meta, root)
    meta.update(status="active", replaced=previous, activated_at=datetime.now(UTC).isoformat())
    write_meta(revision, meta, root)
    (registry_root(root) / "active").write_text(revision + "\n")
    return previous


def rollback(root=None):
    """Return to the revision that the active one replaced."""
    current = active_revision(root)
    meta = read_meta(current, root)
    previous = meta.get("replaced")
    if not previous:
        raise RegistryError(f"{current} did not replace another revision; nothing to roll back to")
    previous_meta = read_meta(previous, root)
    meta.update(status="rolled_back", rolled_back_at=datetime.now(UTC).isoformat())
    write_meta(current, meta, root)
    previous_meta["status"] = "active"
    write_meta(previous, previous_meta, root)
    (registry_root(root) / "active").write_text(previous + "\n")
    return current, previous
