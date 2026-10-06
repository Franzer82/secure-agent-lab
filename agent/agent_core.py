import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import anyio
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from mcp import Client, StdioServerParameters
from mcp.types import TextContent

GEMINI_MODEL = "gemini-3.8-flash"

DEFAULT_MAX_STEPS = 6
MAX_ATTEMPTS = 3
SERVER_ERROR_PAUSE_SECONDS = 5
RATE_LIMIT_PAUSE_SECONDS = 20


# ---------------------------------------------------------------------------
# Datenstrukturen
# ---------------------------------------------------------------------------

@dataclass
class PolicyDecision:
    """Ergebnis der Policy-Prüfung für einen einzelnen Tool-Aufruf."""
    allowed: bool
    reason: str = ""


# Eine Policy ist eine Funktion: (Tool-Name, Argumente) -> Entscheidung.
Policy = Callable[[str, dict], PolicyDecision]


def allow_all_policy(tool_name: str, args: dict) -> PolicyDecision:
    """Version 1: Es wird alles erlaubt. Genau das ist die Schwäche - der Agent
    führt jeden Wunsch des Modells ungeprüft aus."""
    return PolicyDecision(allowed=True)


@dataclass
class ToolCallRecord:
    """Ein protokollierter Tool-Aufruf. Die Angriffs-Suite wertet diese Spur
    automatisch aus."""
    name: str
    args: dict
    allowed: bool
    is_error: bool
    result_text: str


@dataclass
class AgentRun:
    """Das vollständige Ergebnis eines Agenten-Laufs.

    'error' ist gefüllt, wenn der Lauf technisch scheiterte (z. B. API-Fehler).
    Solche Läufe dürfen in der Auswertung NICHT als 'Angriff abgewehrt' zählen,
    sondern müssen aussortiert werden - sonst verfälschen sie die Messung."""
    user_message: str
    final_text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    steps: int = 0
    error: str = ""


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _text_of(result) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


def _create_gemini_client() -> genai.Client:
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY nicht gefunden (.env prüfen)")
    return genai.Client(api_key=api_key)


async def _generate_with_retry(gemini: genai.Client, contents: list, config: types.GenerateContentConfig):
    """Ruft Gemini auf und wiederholt bei vorübergehenden Fehlern: Serverfehler
    auf Googles Seite (5xx) und Anfragelimit (429). Alle anderen Fehler (z. B.
    ungültiger Schlüssel) werden sofort weitergegeben, denn Warten hilft dort nicht."""
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await gemini.aio.models.generate_content(
                model=GEMINI_MODEL, contents=contents, config=config
            )
        except errors.ServerError as error:
            last_error = error
            pause = SERVER_ERROR_PAUSE_SECONDS * attempt
        except errors.ClientError as error:
            if getattr(error, "code", None) != 429:
                raise
            last_error = error
            pause = RATE_LIMIT_PAUSE_SECONDS

        if attempt < MAX_ATTEMPTS:
            await anyio.sleep(pause)

    raise last_error


async def _execute_tool_call(mcp_client: Client, policy: Policy, name: str, args: dict) -> ToolCallRecord:
    """Prüft einen Tool-Wunsch des Modells gegen die Policy und führt ihn nur bei
    Erlaubnis über MCP aus. Das ist der zentrale Durchsetzungspunkt: Die
    Berechtigung wird AUSSERHALB des Modells entschieden."""
    decision = policy(name, args)
    if not decision.allowed:
        return ToolCallRecord(
            name=name, args=args, allowed=False, is_error=True,
            result_text=f"Aktion abgelehnt: {decision.reason}",
        )

    try:
        result = await mcp_client.call_tool(name, args)
    except Exception as error:
        return ToolCallRecord(
            name=name, args=args, allowed=True, is_error=True,
            result_text=f"Tool-Fehler ({type(error).__name__})",
        )

    return ToolCallRecord(
        name=name, args=args, allowed=True,
        is_error=bool(result.is_error), result_text=_text_of(result),
    )


# ---------------------------------------------------------------------------
# Die Agenten-Schleife
# ---------------------------------------------------------------------------

async def run_agent(
    user_message: str,
    *,
    server_path: Path,
    system_prompt: str,
    policy: Policy = allow_all_policy,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> AgentRun:
    gemini = _create_gemini_client()

    # Der Server-Unterprozess bekommt nur PATH mit - NICHT deine übrigen
    # Umgebungsvariablen (insbesondere nicht den API-Schlüssel).
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(server_path)],
        env={"PATH": os.environ.get("PATH", "")},
    )

    run = AgentRun(user_message=user_message, final_text="")

    async with Client(server_params) as mcp_client:
        listed = await mcp_client.list_tools()

        # Die Tool-Beschreibungen des Servers (inkl. JSON-Schema der Argumente)
        # werden an Gemini weitergereicht.
        declarations = [
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or tool.name,
                parameters_json_schema=tool.input_schema,
            )
            for tool in listed.tools
        ]

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(function_declarations=declarations)],
            # WICHTIGSTE ZEILE: Das SDK darf Tools NICHT selbst ausführen,
            # sonst würde unsere Policy-Schicht umgangen.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_message)])]

        for step in range(1, max_steps + 1):
            run.steps = step

            # API-Fehler hier abfangen und im Lauf vermerken, statt sie durch den
            # async-with-Block nach außen fliegen zu lassen (dort würden sie in
            # unleserliche Exception Groups verpackt).
            try:
                response = await _generate_with_retry(gemini, contents, config)
            except errors.APIError as error:
                run.error = f"Gemini-Fehler (Code {getattr(error, 'code', '?')}, {getattr(error, 'status', '?')})"
                run.final_text = f"(Lauf abgebrochen: {run.error})"
                return run

            if not response.candidates or response.candidates[0].content is None:
                run.final_text = "(Keine Antwort vom Modell erhalten.)"
                return run

            # Die komplette Modell-Antwort UNVERÄNDERT in den Verlauf: Gemini-3-
            # Modelle brauchen die darin enthaltenen "Thought Signatures".
            contents.append(response.candidates[0].content)

            calls = response.function_calls or []
            if not calls:
                run.final_text = response.text or ""
                return run

            response_parts = []
            for call in calls:
                args = dict(call.args or {})
                record = await _execute_tool_call(mcp_client, policy, call.name, args)
                run.tool_calls.append(record)

                key = "error" if record.is_error else "output"
                response_parts.append(
                    types.Part.from_function_response(name=call.name, response={key: record.result_text})
                )

            # Tool-Ergebnisse gehen als Rolle "user" zurück (die API lehnt "tool" ab).
            contents.append(types.Content(role="user", parts=response_parts))

        run.final_text = f"(Abbruch: maximale Schrittzahl {max_steps} erreicht.)"
        return run