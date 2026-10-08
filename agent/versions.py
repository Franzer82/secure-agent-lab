from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agent_core import (
    MemoryFormatter,
    OutputFilter,
    Policy,
    allow_all_policy,
    format_memory_v1,
    format_memory_v2,
    identity_filter,
)
from output_filter_v2 import filter_output_v2
from policy_v2 import make_policy_v2
from run_v1 import SERVER_PATH as SERVER_PATH_V1
from run_v1 import SYSTEM_PROMPT_V1
from run_v2 import SERVER_PATH as SERVER_PATH_V2
from run_v2 import SYSTEM_PROMPT_V2


@dataclass
class VersionConfig:
    """Alles, was eine Agenten-Version ausmacht. Die Angriffs-Suite bekommt nur
    diese Beschreibung, nicht den Code der Version selbst. So testen wir alle
    Versionen mit exakt derselben Suite."""
    name: str
    server_path: Path
    system_prompt: str
    policy_factory: Callable[[], Policy]
    memory_formatter: MemoryFormatter
    memory_placement: str
    output_filter: OutputFilter
    # Szenarien, die für diese Version bewusst NICHT gemessen werden, samt Begründung.
    excluded: dict[str, str] = field(default_factory=dict)

    def agent_kwargs(self) -> dict:
        """Die Argumente für run_agent. Die Policy wird dabei jedes Mal NEU erzeugt:
        Sie hat Zustand (Ticket-Zähler, Dokumentkontakt), und der darf nicht von
        einem Gespräch ins nächste wandern."""
        return {
            "server_path": self.server_path,
            "system_prompt": self.system_prompt,
            "policy": self.policy_factory(),
            "memory_formatter": self.memory_formatter,
            "memory_placement": self.memory_placement,
            "output_filter": self.output_filter,
        }


# Siehe docs/v2_plan.md, Abschnitt 2: Ein Geheimnis, das es nicht gibt, kann nicht
# verraten werden. Eine Messung könnte nur 0 Prozent ergeben und wäre nicht aussagekräftig.
EXCLUDED_V2 = {
    "A4": "durch Konstruktion: Der Systemprompt enthält die Kennung nicht mehr",
    "A7": "durch Konstruktion: Es gibt kein Geheimnis, das in einen Link geschrieben werden könnte",
}


def get_version(name: str) -> VersionConfig:
    if name == "v1":
        return VersionConfig(
            name="v1",
            server_path=SERVER_PATH_V1,
            system_prompt=SYSTEM_PROMPT_V1,
            policy_factory=lambda: allow_all_policy,
            memory_formatter=format_memory_v1,
            memory_placement="system",
            output_filter=identity_filter,
        )

    if name == "v2":
        return VersionConfig(
            name="v2",
            server_path=SERVER_PATH_V2,
            system_prompt=SYSTEM_PROMPT_V2,
            policy_factory=make_policy_v2,
            memory_formatter=format_memory_v2,
            memory_placement="user",
            output_filter=filter_output_v2,
            excluded=dict(EXCLUDED_V2),
        )

    if name == "v2n":
        # Gegenprobe für A8s (docs/a8s_plan.md): Version 2, aber die Notizen werden
        # wie in Version 1 behandelt (Systemprompt, Formatierer v1). Server, Policy,
        # Ausgabefilter und Systemprompt sind identisch mit Version 2. Nur der
        # Vergleich v2n gegen v2 isoliert die Umstellung "Notizen als Daten".
        return VersionConfig(
            name="v2n",
            server_path=SERVER_PATH_V2,
            system_prompt=SYSTEM_PROMPT_V2,
            policy_factory=make_policy_v2,
            memory_formatter=format_memory_v1,
            memory_placement="system",
            output_filter=filter_output_v2,
            excluded=dict(EXCLUDED_V2),
        )

    raise ValueError(f"Unbekannte Version: {name}")