import sys
from pathlib import Path

import anyio

from agent_core import format_memory_v2, run_agent
from output_filter_v2 import filter_output_v2
from policy_v2 import make_policy_v2
from run_v1 import SYSTEM_PROMPT_V1

SERVER_PATH = Path(__file__).resolve().parent.parent / "mcp_server" / "server_v2.py"

# Der Systemprompt von Version 2 ist der von Version 1 OHNE die Zeile mit der
# Kennung: Ein Prompt kann ausgelesen werden, deshalb gehört kein Geheimnis
# hinein. Er enthält bewusst KEINE zusätzlichen Sicherheitsanweisungen (siehe
# docs/v2_plan.md). Er wird aus dem Prompt von Version 1 abgeleitet, damit
# "sonst unverändert" nicht nur behauptet, sondern geprüft werden kann.
SYSTEM_PROMPT_V2 = "\n".join(
    line for line in SYSTEM_PROMPT_V1.splitlines() if "LAB-CANARY" not in line
)


async def main(question: str) -> None:
    print(f"Frage: {question}\n")

    run = await run_agent(
        question,
        server_path=SERVER_PATH,
        system_prompt=SYSTEM_PROMPT_V2,
        policy=make_policy_v2(),  # eine NEUE Policy pro Gespräch
        memory_formatter=format_memory_v2,
        memory_placement="user",
        output_filter=filter_output_v2,
    )

    if run.error:
        print(run.error)
        sys.exit(1)

    if run.memory_text:
        print(f"Geladene Notizen: {len(run.memory_text.splitlines())}")

    if run.tool_calls:
        print("Tool-Aufrufe:")
        for call in run.tool_calls:
            status = "erlaubt" if call.allowed else "ABGELEHNT"
            suffix = ", Fehler" if call.is_error else ""
            print(f"  - {call.name} {call.args} [{status}{suffix}]")
    else:
        print("Keine Tool-Aufrufe.")

    if run.raw_text and run.raw_text != run.final_text:
        print("\nDer Ausgabefilter hat die Antwort verändert. Antwort des Modells VOR dem Filter:")
        print(run.raw_text)

    print(f"\nAntwort ({run.steps} Schritt(e)):\n{run.final_text}")


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "Wie richte ich das VPN ein?"
    anyio.run(main, question)