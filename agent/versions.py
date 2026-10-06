from dataclasses import dataclass
from pathlib import Path

from agent_core import MemoryFormatter, Policy, allow_all_policy, format_memory_v1
from run_v1 import SERVER_PATH as SERVER_PATH_V1
from run_v1 import SYSTEM_PROMPT_V1


@dataclass
class VersionConfig:
    """Alles, was eine Agenten-Version ausmacht. Die Angriffs-Suite bekommt nur
    diese Beschreibung, nicht den Code der Version selbst. So testen wir v1 und
    später v2 mit exakt derselben Suite."""
    name: str
    server_path: Path
    system_prompt: str
    policy: Policy
    memory_formatter: MemoryFormatter


def get_version(name: str) -> VersionConfig:
    if name == "v1":
        return VersionConfig(
            name="v1",
            server_path=SERVER_PATH_V1,
            system_prompt=SYSTEM_PROMPT_V1,
            policy=allow_all_policy,
            memory_formatter=format_memory_v1,
        )
    raise ValueError(f"Unbekannte Version: {name}")