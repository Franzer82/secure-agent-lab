import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import anyio

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_core import GEMINI_MODEL, run_agent  # noqa: E402
from lab_settings import DAILY_BUDGET  # noqa: E402
from lab_state import reset_all  # noqa: E402
from scenarios import SCENARIOS, Scenario, cleanup_fixtures, install_fixture  # noqa: E402
from usage_budget import remaining_today  # noqa: E402
from versions import VersionConfig, get_version  # noqa: E402

REPORTS_DIR = BASE_DIR / "reports"
RAW_DIR = REPORTS_DIR / "raw"

# Nach so vielen technischen Fehlern in Folge brechen wir ab, statt weitere
# Anfragen zu verschwenden.
MAX_CONSECUTIVE_ERRORS = 3

# Pro Szenario höchstens so viele Versuche insgesamt (gültige und fehlerhafte)
# wie Ziel mal diesem Faktor. Verhindert eine Endlosschleife bei einem
# dauerhaften Fehler.
MAX_ATTEMPT_FACTOR = 2

# Obergrenze der Anfragen, die ein einzelner Versuch brauchen kann (zwei
# Agenten-Läufe mit je bis zu 6 Schritten, plus Reserve). Wir starten nur dann
# einen Versuch, wenn das Tagesbudget dafür reicht - so wird das Limit nie
# mitten in einem Versuch überrannt.
MIN_REQUESTS_PER_TRIAL = 14


@dataclass
class Trial:
    """Ein einzelner Versuch. Status: 'ja' (Kriterium erfüllt), 'nein' oder 'fehler'
    (technisches Problem, wird aus der Auswertung herausgenommen). Die gespeicherten
    Läufe enthalten alle Tool-Aufrufe und die Antwort VOR und NACH dem Ausgabefilter."""
    scenario_id: str
    status: str
    detail: str
    model: str
    timestamp: str
    stages: dict = field(default_factory=dict)
    runs: list = field(default_factory=list)


def describe_exception(error: BaseException) -> str:
    """Nennt den Fehlertyp. Bei einer ExceptionGroup (einem Sammelbehälter für
    mehrere Fehler aus asynchronen Aufgaben) werden die inneren Fehlertypen
    mit ausgegeben. Es werden nur Typnamen ausgegeben, keine Fehlertexte."""
    if isinstance(error, BaseExceptionGroup):
        inner = ", ".join(describe_exception(item) for item in error.exceptions)
        return f"{type(error).__name__}[{inner}]"
    return type(error).__name__


# ---------------------------------------------------------------------------
# Speicher: Jeder Versuch wird sofort in eine Datei geschrieben
# ---------------------------------------------------------------------------

def store_path(version: str) -> Path:
    return RAW_DIR / f"trials_{version}.jsonl"


def load_trials(version: str) -> list[dict]:
    path = store_path(version)
    if not path.exists():
        return []
    trials = []
    with open(path, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                trials.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return trials


def append_trial(version: str, trial: Trial) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with open(store_path(version), "a", encoding="utf-8") as file:
        file.write(json.dumps(asdict(trial), ensure_ascii=False) + "\n")


def trials_for(version: str, scenario_id: str) -> list[dict]:
    """Nur Versuche mit dem AKTUELLEN Modell zählen. Quoten verschiedener Modelle
    dürfen nie vermischt werden."""
    return [
        t for t in load_trials(version)
        if t["scenario_id"] == scenario_id and t["model"] == GEMINI_MODEL
    ]


# ---------------------------------------------------------------------------
# Ein Versuch
# ---------------------------------------------------------------------------

async def run_trial(scenario: Scenario, config: VersionConfig) -> Trial:
    # Jeder Versuch beginnt mit sauberem Zustand: Gedächtnis, Tickets, E-Mails und
    # präparierte Dokumente vom letzten Versuch dürfen das Ergebnis nicht beeinflussen.
    reset_all()
    cleanup_fixtures()
    install_fixture(scenario)

    timestamp = datetime.now().isoformat(timespec="seconds")
    runs = []

    try:
        for message in scenario.messages:
            # agent_kwargs() erzeugt für JEDES Gespräch eine neue Policy. Szenarien
            # mit zwei Nachrichten (A8, K5) sind zwei getrennte Gespräche.
            run = await run_agent(message, **config.agent_kwargs())
            runs.append(run)
            if run.error:
                break
    except Exception as error:
        return Trial(scenario.id, "fehler", f"Ausnahme: {describe_exception(error)}", GEMINI_MODEL, timestamp)
    finally:
        cleanup_fixtures()

    if any(run.error for run in runs):
        return Trial(
            scenario.id, "fehler", "; ".join(run.error for run in runs if run.error),
            GEMINI_MODEL, timestamp,
        )

    outcome = scenario.evaluate(runs)
    return Trial(
        scenario.id, "ja" if outcome.success else "nein", outcome.detail,
        GEMINI_MODEL, timestamp, outcome.stages, [asdict(run) for run in runs],
    )


def label(scenario: Scenario, trial: Trial) -> str:
    if trial.status == "fehler":
        return "TECHNISCHER FEHLER (aussortiert)"
    if scenario.kind == "attack":
        return "Angriff ERFOLGREICH" if trial.status == "ja" else "Angriff abgewehrt"
    return "bestanden" if trial.status == "ja" else "NICHT bestanden"


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------

def summarize(scenario: Scenario, trials: list[dict]) -> dict:
    valid = [t for t in trials if t["status"] != "fehler"]
    wins = sum(1 for t in valid if t["status"] == "ja")

    stage_text = ""
    stage_keys = sorted({key for t in valid for key in t.get("stages", {})})
    if stage_keys:
        stage_text = ", ".join(
            f"{key}: {sum(1 for t in valid if t['stages'].get(key))}/{len(valid)}" for key in stage_keys
        )

    return {
        "id": scenario.id, "title": scenario.title, "kind": scenario.kind,
        "route": scenario.route, "owasp": scenario.owasp,
        "valid": len(valid), "wins": wins, "errors": len(trials) - len(valid),
        "rate": (wins / len(valid)) if valid else None,
        "stage_text": stage_text,
    }


def percent(rate) -> str:
    return "n/a" if rate is None else f"{rate:.0%}"


def build_summary(version: str, target_runs: int, rows: list[dict], excluded: dict[str, str]) -> str:
    attacks = [r for r in rows if r["kind"] == "attack"]
    controls = [r for r in rows if r["kind"] == "control"]

    lines = [
        f"# Ergebnisse der Angriffs-Suite: Version {version}",
        "",
        f"- Stand: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- Modell: {GEMINI_MODEL}",
        f"- Ziel: {target_runs} gültige Läufe je Szenario",
        "- Läufe mit technischem Fehler sind aussortiert und separat gezählt.",
        "- Hinweis: Bei wenigen Läufen ist die Quote nur eine grobe Schätzung.",
        "- Die Ergebnisse gelten für das genannte Modell, nicht für Gemini allgemein.",
        "- Szenarien mit Kleinbuchstaben am Ende (A2b, A3b, A7b) sind Nachträge, siehe docs/nachtraege.md.",
        "",
        "## Angriffe (Erfolgsquote: niedriger ist besser)",
        "",
        "| ID | Szenario | Weg | OWASP | Gültige Läufe | Erfolgreich | Quote | Technische Fehler | Stufen |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in attacks:
        if r["id"] in excluded:
            lines.append(
                f"| {r['id']} | {r['title']} | {r['route']} | {r['owasp']} | - | - | "
                f"nicht gemessen | - | {excluded[r['id']]} |"
            )
            continue
        lines.append(
            f"| {r['id']} | {r['title']} | {r['route']} | {r['owasp']} | {r['valid']} | "
            f"{r['wins']} | {percent(r['rate'])} | {r['errors']} | {r['stage_text'] or '-'} |"
        )

    lines += [
        "",
        "## Kontrollfälle (Funktionserhalt: höher ist besser)",
        "",
        "| ID | Aufgabe | Gültige Läufe | Bestanden | Quote | Technische Fehler | Stufen |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in controls:
        lines.append(
            f"| {r['id']} | {r['title']} | {r['valid']} | {r['wins']} | "
            f"{percent(r['rate'])} | {r['errors']} | {r['stage_text'] or '-'} |"
        )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------

async def main(args: argparse.Namespace) -> None:
    config = get_version(args.version)
    path = store_path(config.name)

    if args.fresh and path.exists():
        backup = path.with_name(f"{path.stem}_alt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")
        path.rename(backup)
        print(f"Vorherige Ergebnisse gesichert als {backup.name}")

    selected = SCENARIOS
    if args.only:
        # Kennungen OHNE Beachtung der Groß-/Kleinschreibung vergleichen: Die
        # Nachträge heißen A2b, A3b, A7b (kleines b), und wer "a2b" oder "A2B"
        # tippt, meint dasselbe.
        wanted = [item.strip().upper() for item in args.only.split(",") if item.strip()]
        known = {s.id.upper() for s in SCENARIOS}
        unknown = [item for item in wanted if item not in known]
        if unknown:
            names = ", ".join(s.id for s in SCENARIOS)
            print(f"Unbekannte Szenarien: {', '.join(unknown)} (bekannt: {names})")
            sys.exit(1)
        selected = [s for s in SCENARIOS if s.id.upper() in wanted]

    # Szenarien, die für diese Version bewusst nicht gemessen werden (Begründung
    # steht in der Versionsbeschreibung und im Messplan), werden übersprungen.
    skipped = [s for s in selected if s.id in config.excluded]
    for scenario in skipped:
        print(f"{scenario.id}: nicht gemessen ({config.excluded[scenario.id]})")
    if skipped:
        print()
    selected = [s for s in selected if s.id not in config.excluded]

    stop_message = ""

    if not args.summary_only:
        print(f"Version {config.name}, Modell {GEMINI_MODEL}, {len(selected)} Szenario(en), "
              f"Ziel: {args.runs} gültige Läufe je Szenario")
        print(f"Tagesbudget: noch {remaining_today(GEMINI_MODEL)} von {DAILY_BUDGET} Anfragen\n")

        consecutive_errors = 0
        try:
            for scenario in selected:
                valid_now = sum(1 for t in trials_for(config.name, scenario.id) if t["status"] != "fehler")
                if valid_now >= args.runs:
                    print(f"{scenario.id}: bereits {valid_now} gültige Läufe, übersprungen")
                    continue

                attempts = 0
                max_attempts = args.runs * MAX_ATTEMPT_FACTOR
                while valid_now < args.runs and attempts < max_attempts:
                    # Vor jedem Versuch prüfen, ob das Tagesbudget dafür reicht.
                    remaining = remaining_today(GEMINI_MODEL)
                    if remaining < MIN_REQUESTS_PER_TRIAL:
                        stop_message = (
                            f"Tagesbudget fast aufgebraucht (noch {remaining} von {DAILY_BUDGET} Anfragen, "
                            f"ein Versuch braucht bis zu {MIN_REQUESTS_PER_TRIAL})."
                        )
                        break

                    attempts += 1
                    trial = await run_trial(scenario, config)
                    append_trial(config.name, trial)

                    if trial.status == "fehler":
                        consecutive_errors += 1
                    else:
                        consecutive_errors = 0
                        valid_now += 1

                    print(f"{scenario.id} Versuch {attempts}, gültig {valid_now}/{args.runs}: {label(scenario, trial)}")
                    print(f"    {trial.detail}")

                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        stop_message = f"{MAX_CONSECUTIVE_ERRORS} technische Fehler in Folge: {trial.detail}"
                        break

                    await anyio.sleep(args.pause)

                if stop_message:
                    break
        finally:
            reset_all()
            cleanup_fixtures()

    rows = [summarize(s, trials_for(config.name, s.id)) for s in SCENARIOS]

    print("\n=== Zusammenfassung (alle bisher gesammelten gültigen Versuche) ===")
    for row in rows:
        if row["valid"] + row["errors"] == 0:
            continue
        kind = "Angriffe" if row["kind"] == "attack" else "Kontrolle"
        extra = f" ({row['stage_text']})" if row["stage_text"] else ""
        print(f"{row['id']:>3} [{kind}] {row['wins']}/{row['valid']} = {percent(row['rate'])}, "
              f"Fehler: {row['errors']}{extra}  {row['title']}")

    REPORTS_DIR.mkdir(exist_ok=True)
    summary_path = REPORTS_DIR / f"summary_{config.name}.md"
    summary_path.write_text(build_summary(config.name, args.runs, rows, config.excluded), encoding="utf-8")
    print(f"\nZusammenfassung: {summary_path.relative_to(BASE_DIR)}")
    print(f"Alle Versuche:   {path.relative_to(BASE_DIR)}")
    print(f"Tagesbudget:     noch {remaining_today(GEMINI_MODEL)} von {DAILY_BUDGET} Anfragen")

    if stop_message:
        print(f"\nABBRUCH: {stop_message}")
        if "429" in stop_message:
            print("Das Anfragekontingent ist vermutlich erschöpft.")
        print("Alle bisherigen Versuche sind gespeichert. Später denselben Befehl erneut ausführen: "
              "es wird dort fortgesetzt, wo aufgehört wurde.")
        sys.exit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Angriffs-Suite für den Secure Agent Lab")
    parser.add_argument("--version", default="v1", help="Zu testende Version (Standard: v1)")
    parser.add_argument("--runs", type=int, default=5, help="Ziel: gültige Läufe pro Szenario (Standard: 5)")
    parser.add_argument("--only", default="", help="Nur diese Szenarien, z. B. K1,A1,A2b (Groß-/Kleinschreibung egal)")
    parser.add_argument("--pause", type=float, default=2.0, help="Zusätzliche Pause zwischen den Versuchen in Sekunden")
    parser.add_argument("--fresh", action="store_true", help="Bisherige Ergebnisse sichern und neu beginnen")
    parser.add_argument("--summary-only", action="store_true", help="Nur die Zusammenfassung neu erstellen (ohne Anfragen)")
    anyio.run(main, parser.parse_args())