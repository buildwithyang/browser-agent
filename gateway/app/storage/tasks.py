from pathlib import Path

from app.models import TaskRecord


class JsonlTaskStore:
    def __init__(self, path: Path | str = "data/tasks.jsonl") -> None:
        self.path = Path(path)

    def append(self, task: TaskRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(task.model_dump_json() + "\n")
