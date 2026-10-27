"""Print the pip requirements of the Home Assistant components the pools front.

The test harness installs Home Assistant but not its components' own
dependencies, and a component that cannot be imported makes its platform
untestable. Reading them from the installed manifests, rather than pinning them
a second time by hand, keeps this correct across the Home Assistant versions
the CI matrix covers: ``scripts/lock.sh`` feeds this output into each
version's hash-locked file, and ``--check`` catches a lock gone stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import homeassistant

# The domains the pools front. Their dependencies are followed transitively,
# which is how tts reaches ffmpeg and ai_task reaches camera.
ROOTS = ("ai_task", "conversation", "stt", "tts", "sensor", "homeassistant")


def collect(root: Path, domain: str, seen: set[str], out: list[str]) -> None:
    """Add ``domain``'s requirements, then those of what it depends on."""
    if domain in seen:
        return
    seen.add(domain)

    manifest = root / domain / "manifest.json"
    if not manifest.exists():
        return

    data = json.loads(manifest.read_text(encoding="utf8"))
    for requirement in data.get("requirements", []):
        if requirement not in out:
            out.append(requirement)
    for dependency in data.get("dependencies", []):
        collect(root, dependency, seen, out)


def requirements() -> list[str]:
    """Return the fronted components' requirements, in discovery order."""
    root = Path(homeassistant.__file__).parent / "components"
    out: list[str] = []
    seen: set[str] = set()
    for domain in ROOTS:
        collect(root, domain, seen, out)

    # ai_task imports camera at module level for its image tasks, so the
    # component cannot be imported without it even though it is not a declared
    # dependency of anything here.
    collect(root, "camera", seen, out)
    return out


def check() -> int:
    """Report requirements the installed environment does not satisfy.

    CI installs a hash-locked file instead of this script's output. Without
    this check a harness bump would test against a stale lock and only fail
    later, on an import, far from the cause.
    """
    from importlib.metadata import PackageNotFoundError, version

    from packaging.requirements import Requirement

    missing = []
    for line in requirements():
        requirement = Requirement(line)
        try:
            installed = version(requirement.name)
        except PackageNotFoundError:
            missing.append(f"{line} (not installed)")
            continue
        if not requirement.specifier.contains(installed, prereleases=True):
            missing.append(f"{line} (installed {installed})")
    for line in missing:
        print(f"Lock is stale: {line}", file=sys.stderr)
    return 1 if missing else 0


def main() -> None:
    """Print one requirement per line, for ``pip install -r``.

    With ``--check``, verify them against the installed environment instead.
    """
    if "--check" in sys.argv[1:]:
        sys.exit(check())
    for requirement in requirements():
        print(requirement)


if __name__ == "__main__":
    main()
