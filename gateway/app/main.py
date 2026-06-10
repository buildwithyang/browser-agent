import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agents.simple import SimpleAgent
from app.config import settings
from app.models import TaskCreate, TaskRecord
from app.storage.tasks import JsonlTaskStore

logger = logging.getLogger("agent_bridge")

app = FastAPI(title="Agent Bridge Gateway")

# The extension posts from arbitrary origins (the page the user is on), so allow
# cross-origin requests to the local gateway.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

store = JsonlTaskStore()
agents = {
    "simple": SimpleAgent(
        api_key=settings.openai_api_key or None,
        base_url=settings.openai_base_url or None,
        model=settings.model,
    ),
}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tasks", response_model=TaskRecord)
def create_task(task: TaskCreate) -> TaskRecord:
    agent = agents.get(task.agent)
    if agent is None:
        raise HTTPException(status_code=400, detail=f"Unsupported agent: {task.agent}")

    prompt = agent.build_prompt(task)
    try:
        result = agent.run(task)
        record = TaskRecord(status="completed", request=task, prompt=prompt, result=result)
    except Exception as exc:  # surface failures to the browser instead of a 500
        logger.exception("Agent run failed")
        record = TaskRecord(status="failed", request=task, prompt=prompt, error=str(exc))

    store.append(record)
    if record.status == "failed":
        raise HTTPException(status_code=502, detail=record.error)
    return record
