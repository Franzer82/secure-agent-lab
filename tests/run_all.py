import re
import subprocess
import sys
from pathlib import Path

# Startet alle Testdateien nacheinander und fasst die Ergebnisse zusammen.
# Keine der Prüfungen stellt eine Gemini-Anfrage.

TESTS_DIR = Path(__file__).resolve().parent
FILES = [
    "test_scenarios.py",
    "test_controls.py",
    "test_server_v2.py",
    "test_agent_v2.py",
    "test_versions.py",
]
SUMMARY = re.compile(r"(\d+) von (\d+) Prüfungen bestanden")


def main() -> None:
    total_ok = 0
    total = 0
    failed_files = []

    for name in FILES:
        process = subprocess.run(
            [sys.executable, str(TESTS_DIR / name)], capture_output=True, text=True
        )
        match = SUMMARY.search(process.stdout)

        if match is None:
            print(f"[FEHLER] {name}: keine Auswertung (Rückgabecode {process.returncode})")
            for line in process.stderr.strip().splitlines()[-6:]:
                print(f"    {line}")
            failed_files.append(name)
            continue

        ok, count = int(match.group(1)), int(match.group(2))
        total_ok += ok
        total += count

        if ok == count and process.returncode == 0:
            print(f"[OK] {name}: {ok} von {count}")
        else:
            print(f"[FEHLER] {name}: {ok} von {count}")
            for line in process.stdout.splitlines():
                if line.startswith("[FEHLER]"):
                    print(f"    {line}")
            failed_files.append(name)

    print(f"\nGesamt: {total_ok} von {total} Prüfungen bestanden.")
    if failed_files:
        sys.exit(1)


if __name__ == "__main__":
    main()