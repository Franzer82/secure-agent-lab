import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Belegt, dass der vorab festgelegte Messplan seit seinem ersten Commit nur
# ERGÄNZT wurde: Die heutige Datei muss mit dem exakten Text der Fassung aus dem
# ersten Commit beginnen.

# Der Commit, in dem der Messplan VOR der ersten Messung von Version 2 festgelegt wurde.
REFERENCE_COMMIT = "05a59c0"


def main() -> None:
    original = subprocess.run(
        ["git", "show", f"{REFERENCE_COMMIT}:docs/v2_plan.md"],
        capture_output=True, text=True, check=True, cwd=BASE_DIR,
    ).stdout
    current = (BASE_DIR / "docs" / "v2_plan.md").read_text(encoding="utf-8")

    unchanged = current.startswith(original)
    print(f"Messplan seit {REFERENCE_COMMIT} nur ergänzt (Anfang unverändert): {unchanged}")

    if not unchanged:
        sys.exit(1)

    print(f"Ergänzt wurden {len(current) - len(original)} Zeichen.")


if __name__ == "__main__":
    main()