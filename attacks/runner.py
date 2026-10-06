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
from lab_state import reset_all  # noqa: E402
from scenarios import SCENARIOS, Scenario, cleanup_fixtures, install_fixture  # noqa: E402
from versions import VersionConfig, get_version  # noqa: E402

REPORTS_DIR = BASE_DIR / "reports"
RAW_DIR = REPORTS_DIR / "raw"


@dataclass
class Trial:
    """Ein einzelner Versuch. Status: 'ja' (Kriterium erfüllt), 'nein' oder 'fehler'
    (technisches Problem, wird aus der Auswertung herausgenommen)."""
    scenario_id: str
    index: int
    status: str
    detail: str
    stages: dict = field(default_factory=dict)
    runs: list = field(default_factory=list)


async def run_trial(scenario: Scenario, config: VersionConfig, index: int) -> Trial:
    # Jeder Versuch beginnt mit sauberem Zustand: Gedächtnis, Tickets, E-Mails und
    # präparierte Dokumente vom letzten Versuch dürfen das Ergebnis nicht beeinflussen.
    reset_all()
    cleanup_fixtures()
    install_fixture(scenario)

    runs = []
    try:
        for message in scenario.messages:
            run = await run_agent(
                message,
                server_path=config.server_path,
                system_prompt=config.system_prompt,
                policy=config.policy,
                memory_formatter=config.memory_formatter,
            )
            runs.append(run)
            if run.error:
                break
    except Exception as error:
        return Trial(scenario.id, index, "fehler", f"Ausnahme: {type(error).__name__}")
    finally:
        cleanup_fixtures()

    if any(run.error for run in runs):
        return Trial(scenario.id, index, "fehler", "; ".join(run.error for run in runs if run.error))

    outcome = scenario.evaluate(runs)
    return Trial(
        scenario.id, index, "ja" if outcome.success else "nein",
        outcome.detail, outcome.stages, [asdict(run) for run in runs],
    )


def label(scenario: Scenario, trial: Trial) -> str:
    if trial.status == "fehler":
        return "TECHNISCHER FEHLER (aussortiert)"
    if scenario.kind == "attack":
        return "Angriff ERFOLGREICH" if trial.status == "ja" else "Angriff abgewehrt"
    return "bestanden" if trial.status == "ja" else "NICHT bestanden"


def summarize(scenario: Scenario, trials: list[Trial]) -> dict:
    valid = [t for t in trials if t.status != "fehler"]
    wins = sum(1 for t in valid if t.status == "ja")

    stage_text = ""
    stage_keys = sorted({key for t in valid for key in t.stages})
    if stage_keys:
        stage_text = ", ".join(
            f"{key}: {sum(1 for t in valid if t.stages.get(key))}/{len(valid)}" for key in stage_keys
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


def build_summary(version: str, runs_per_scenario: int, rows: list[dict]) -> str:
    attacks = [r for r in rows if r["kind"] == "attack"]
    controls = [r for r in rows if r["kind"] == "control"]

    lines = [
        f"# Ergebnisse der Angriffs-Suite: Version {version}",
        "",
        f"- Stand: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- Modell: {GEMINI_MODEL}",
        f"- Läufe pro Szenario: {runs_per_scenario}",
        "- Läufe mit technischem Fehler sind aussortiert und separat gezählt.",
        "- Hinweis: Bei wenigen Läufen ist die Quote nur eine grobe Schätzung.",
        "",
        "## Angriffe (Erfolgsquote: niedriger ist besser)",
        "",
        "| ID | Szenario | Weg | OWASP | Gültige Läufe | Erfolgreich | Quote | Technische Fehler | Stufen |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in attacks:
        lines.append(
            f"| {r['id']} | {r['title']} | {r['route']} | {r['owasp']} | {r['valid']} | "
            f"{r['wins']} | {percent(r['rate'])} | {r['errors']} | {r['stage_text'] or '-'} |"
        )

    lines += [
        "",
        "## Kontrollfälle (Funktionserhalt: höher ist besser)",
        "",
        "| ID | Aufgabe | Gültige Läufe | Bestanden | Quote | Technische Fehler |",
        "|---|---|---|---|---|---|",
    ]
    for r in controls:
        lines.append(
            f"| {r['id']} | {r['title']} | {r['valid']} | {r['wins']} | "
            f"{percent(r['rate'])} | {r['errors']} |"
        )

    return "\n".join(lines) + "\n"


async def main(args: argparse.Namespace) -> None:
    config = get_version(args.version)

    selected = SCENARIOS
    if args.only:
        wanted = [item.strip().upper() for item in args.only.split(",")]
        known = {s.id for s in SCENARIOS}
        unknown = [item for item in wanted if item not in known]
        if unknown:
            print(f"Unbekannte Szenarien: {', '.join(unknown)} (bekannt: {', '.join(sorted(known))})")
            sys.exit(1)
        selected = [s for s in SCENARIOS if s.id in wanted]

    print(f"Version {config.name}, {len(selected)} Szenario(en), {args.runs} Lauf/Läufe je Szenario\n")

    all_trials: dict[str, list[Trial]] = {}
    try:
        for scenario in selected:
            trials = []
            for index in range(1, args.runs + 1):
                trial = await run_trial(scenario, config, index)
                trials.append(trial)
                print(f"{scenario.id} Lauf {index}/{args.runs}: {label(scenario, trial)}")
                print(f"    {trial.detail}")
                await anyio.sleep(args.pause)
            all_trials[scenario.id] = trials
    finally:
        reset_all()
        cleanup_fixtures()

    rows = [summarize(s, all_trials[s.id]) for s in selected]

    print("\n=== Zusammenfassung ===")
    for row in rows:
        kind = "Angriffe" if row["kind"] == "attack" else "Kontrolle"
        extra = f" ({row['stage_text']})" if row["stage_text"] else ""
        print(f"{row['id']:>3} [{kind}] {row['wins']}/{row['valid']} = {percent(row['rate'])}, "
              f"Fehler: {row['errors']}{extra}  {row['title']}")

    # Rohdaten (mit allen Tool-Aufrufen) immer sichern, sie sind git-ignoriert.
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = RAW_DIR / f"{config.name}_{stamp}.json"
    raw_path.write_text(
        json.dumps({k: [asdict(t) for t in v] for k, v in all_trials.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nRohdaten: {raw_path.relative_to(BASE_DIR)}")

    # Die Zusammenfassung nur bei einem VOLLSTÄNDIGEN Lauf schreiben, damit ein
    # Teillauf (--only) nicht die vollständigen Ergebnisse überschreibt.
    if args.only:
        print("Teillauf (--only): Zusammenfassung wird nicht geschrieben.")
    else:
        summary_path = REPORTS_DIR / f"summary_{config.name}.md"
        summary_path.write_text(build_summary(config.name, args.runs, rows), encoding="utf-8")
        print(f"Zusammenfassung: {summary_path.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Angriffs-Suite für den Secure Agent Lab")
    parser.add_argument("--version", default="v1", help="Zu testende Version (Standard: v1)")
    parser.add_argument("--runs", type=int, default=5, help="Läufe pro Szenario (Standard: 5)")
    parser.add_argument("--only", default="", help="Nur diese Szenarien, z. B. K1,A1")
    parser.add_argument("--pause", type=float, default=4.0, help="Pause zwischen den Läufen in Sekunden")
    anyio.run(main, parser.parse_args())