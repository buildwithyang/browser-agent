from abc import ABC, abstractmethod

from app.models import TaskCreate


class AgentAdapter(ABC):
    name: str

    @abstractmethod
    def build_prompt(self, task: TaskCreate) -> str:
        """Render the browser context into a single user-message prompt."""
        raise NotImplementedError

    @abstractmethod
    def run(self, task: TaskCreate) -> str:
        """Execute the task and return the agent's result text."""
        raise NotImplementedError
