from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class BaseTelemetryEvent(ABC):
    @property
    @abstractmethod
    def event_name(self) -> str:
        pass

    @property
    def properties(self) -> dict[str,Any]:
        return {k: v for k, v in asdict(self).items()}
    
@dataclass
class AgentTelemetryEvent(BaseTelemetryEvent):
    query: str
    steps: int
    model:str
    provider:str
    answer: str | None=None
    error: str | None=None
    event_name: str = "agent_event"
    is_success:bool=False
    
