import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "agent"))
sys.path.insert(0, str(BASE_DIR / "attacks"))

import scenarios as sc  # noqa: E402
from agent_core import allow_all_policy, format_memory_v1, format_memory_v2, identity_filter  # noqa: E402
from output_filter_v2 import filter_output_v2  # noqa: E402
from policy_v2 import PolicyV2  # noqa: E402
from run_v1 import SYSTEM_PROMPT_V1  # noqa: E402
from run_v2 import SYSTEM_PROMPT_V2  # noqa: E402
from versions import get_version  # noqa: E402

# Diese Prüfungen testen, dass die Versionen so zusammengesetzt sind, wie der
# Messplan es beschreibt. Es wird keine Gemini-Anfrage gestellt.

results: list[tuple[str, bool]] = []

TICKET = ("create_ticket", {"title": "t", "description": "d"})


def check(label: str, condition: bool) -> None:
    results.append((label, condition))
    print(f"[{'OK' if condition else 'FEHLER'}] {label}")


def test_v1() -> None:
    v1 = get_version("v1")
    kwargs = v1.agent_kwargs()

    check("v1: Policy erlaubt alles (unverändert)", kwargs["policy"] is allow_all_policy)
    check("v1: Notizen im Systemprompt, Formatierer v1",
          kwargs["memory_placement"] == "system" and kwargs["memory_formatter"] is format_memory_v1)
    check("v1: Ausgabefilter verändert nichts", kwargs["output_filter"] is identity_filter)
    check("v1: Systemprompt unverändert und mit Kennung",
          kwargs["system_prompt"] == SYSTEM_PROMPT_V1 and "LAB-CANARY-SYSPROMPT-3310" in kwargs["system_prompt"])
    check("v1: nichts ist ausgeschlossen", v1.excluded == {})
    check("v1: Server ist server_v1.py",
          kwargs["server_path"].name == "server_v1.py" and kwargs["server_path"].exists())


def test_v2() -> None:
    v2 = get_version("v2")
    kwargs = v2.agent_kwargs()

    check("v2: Policy ist die Policy v2", isinstance(kwargs["policy"], PolicyV2))
    check("v2: Notizen als Daten im Nutzer-Block, Formatierer v2",
          kwargs["memory_placement"] == "user" and kwargs["memory_formatter"] is format_memory_v2)
    check("v2: Ausgabefilter ist der Filter v2", kwargs["output_filter"] is filter_output_v2)
    check("v2: Server ist server_v2.py",
          kwargs["server_path"].name == "server_v2.py" and kwargs["server_path"].exists())

    v1_lines = SYSTEM_PROMPT_V1.splitlines()
    v2_lines = SYSTEM_PROMPT_V2.splitlines()
    expected = [line for line in v1_lines if "LAB-CANARY" not in line]

    check("v2: Systemprompt enthält keine Kennung mehr", "LAB-CANARY" not in SYSTEM_PROMPT_V2)
    check("v2: Systemprompt ist der von v1 ohne die Kennungs-Zeile, sonst unverändert",
          len(v1_lines) - len(v2_lines) == 1 and v2_lines == expected)
    check("v2: dieser Systemprompt wird tatsächlich verwendet", kwargs["system_prompt"] == SYSTEM_PROMPT_V2)

    check("v2: A4 und A7 sind 'durch Konstruktion' ausgeschlossen, mit Begründung",
          set(v2.excluded) == {"A4", "A7"} and all(v2.excluded.values()))
    check("Ausgeschlossene Szenarien gibt es in der Szenario-Tabelle",
          set(v2.excluded) <= {s.id for s in sc.SCENARIOS})


def test_state() -> None:
    v2 = get_version("v2")

    first = v2.agent_kwargs()["policy"]
    for _ in range(3):
        first(*TICKET)
    check("v2: das vierte Ticket eines Gesprächs wird blockiert", not first(*TICKET).allowed)

    second = v2.agent_kwargs()["policy"]
    check("v2: jede Anfrage liefert eine NEUE Policy mit frischem Zähler",
          second is not first and second(*TICKET).allowed)

    first("search_knowledge", {"query": "VPN"})
    third = v2.agent_kwargs()["policy"]
    check("v2: Dokumentkontakt wird nicht in das nächste Gespräch übertragen",
          not first("save_note", {"text": "x"}).allowed and third("save_note", {"text": "x"}).allowed)


def test_unknown() -> None:
    try:
        get_version("v9")
        raised = False
    except ValueError:
        raised = True
    check("Unbekannte Version wird abgelehnt", raised)


def main() -> None:
    test_v1()
    test_v2()
    test_state()
    test_unknown()

    failed = [label for label, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} von {len(results)} Prüfungen bestanden.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()