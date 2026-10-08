import dataclasses
import importlib.util
import inspect
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "agent"))
sys.path.insert(0, str(BASE_DIR / "attacks"))

# Belegt, dass die Baseline-Szenarien seit der Vorab-Festlegung inhaltlich
# unverändert sind. Verglichen wird NICHT der Text, sondern die Bedeutung: Titel,
# Nachrichten, präparierte Dokumente und der Quelltext jeder Auswertungsfunktion.
# Ein geänderter Kommentar fällt dabei nicht auf, eine geänderte Auswertung
# schon - und genau auf Letzteres kommt es an.

# Der Commit, in dem die Nachträge VOR der Messung festgelegt wurden.
REFERENCE_COMMIT = "6b9cf30"

CONSTANT_TYPES = (str, int, float, tuple, frozenset)
SCENARIO_FIELDS = ["title", "kind", "route", "owasp", "messages", "fixture_content"]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    old_source = subprocess.run(
        ["git", "show", f"{REFERENCE_COMMIT}:attacks/scenarios.py"],
        capture_output=True, text=True, check=True, cwd=BASE_DIR,
    ).stdout

    differences: list[str] = []

    with tempfile.TemporaryDirectory() as folder:
        old_path = Path(folder) / "scenarios_alt.py"
        old_path.write_text(old_source, encoding="utf-8")
        old = load(old_path, "scenarios_alt")
        new = load(BASE_DIR / "attacks" / "scenarios.py", "scenarios_neu")

        # 1. Jedes bisherige Szenario muss inhaltlich identisch sein.
        new_by_id = {s.id: s for s in new.SCENARIOS}
        for old_scenario in old.SCENARIOS:
            new_scenario = new_by_id.get(old_scenario.id)
            if new_scenario is None:
                differences.append(f"{old_scenario.id}: fehlt in der neuen Fassung")
                continue
            for name in SCENARIO_FIELDS:
                if getattr(old_scenario, name) != getattr(new_scenario, name):
                    differences.append(f"{old_scenario.id}: Feld '{name}' unterscheidet sich")
            if inspect.getsource(old_scenario.evaluate) != inspect.getsource(new_scenario.evaluate):
                differences.append(f"{old_scenario.id}: Quelltext der Auswertung unterscheidet sich")

        # 2. Alle Funktionen und Konstanten, die es schon gab, müssen unverändert sein.
        for name, value in vars(old).items():
            if name.startswith("__") or name == "SCENARIOS" or not hasattr(new, name):
                continue
            new_value = getattr(new, name)
            if inspect.isfunction(value):
                if inspect.getsource(value) != inspect.getsource(new_value):
                    differences.append(f"Funktion {name}: Quelltext unterscheidet sich")
            elif isinstance(value, CONSTANT_TYPES) and value != new_value:
                differences.append(f"Konstante {name}: Wert unterscheidet sich")

        # 3. Die Felder der Scenario-Klasse müssen gleich sein.
        if [f.name for f in dataclasses.fields(old.Scenario)] != [f.name for f in dataclasses.fields(new.Scenario)]:
            differences.append("Scenario: die Felder unterscheiden sich")

        compared = len(old.SCENARIOS)
        added = sorted(set(new_by_id) - {s.id for s in old.SCENARIOS})

    print(f"Verglichen: {compared} bisherige Szenarien samt Auswertung (Referenz: {REFERENCE_COMMIT}).")
    print(f"Neu hinzugekommen: {', '.join(added) or 'keine'}")

    if differences:
        print("\nUNTERSCHIEDE GEFUNDEN:")
        for line in differences:
            print(f"  - {line}")
        sys.exit(1)

    print("Inhaltlich unverändert: keine Abweichung bei Szenarien, Auswertungen und Konstanten.")


if __name__ == "__main__":
    main()