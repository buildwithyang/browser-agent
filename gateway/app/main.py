import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agents.job_match import JobMatchAgent
from app.agents.summary_page import SummaryPageAgent
from app.config import settings
from app.models import TaskCreate, TaskRecord
from app.render import render_markdown
from app.storage.tasks import JsonlTaskStore

# Configure our own logger so task activity prints to the terminal regardless of
# uvicorn's logging setup.
logger = logging.getLogger("agent_bridge")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s [agent-bridge] %(levelname)s %(message)s")
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

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
_agent_opts: dict[str, Any] = dict(
    api_key=settings.openai_api_key or None,
    base_url=settings.openai_base_url or None,
    model=settings.model,
    model_long=settings.model_long or None,
    route_threshold_chars=settings.route_threshold_chars,
)
agents = {
    "summary_page": SummaryPageAgent(**_agent_opts),
    "job_match": JobMatchAgent(**_agent_opts),
}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tasks", response_model=TaskRecord)
def create_task(task: TaskCreate) -> TaskRecord:
    agent = agents.get(task.agent)
    if agent is None:
        raise HTTPException(status_code=400, detail=f"Unsupported agent: {task.agent}")

    logger.info("task received agent=%s url=%s", task.agent, task.url)

    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    prompt = ""
    model = settings.model
    try:
        prompt = agent.build_prompt(task)
        # 路由后实际使用的模型(测试中的 fake agent 没有 pick_model)。
        if hasattr(agent, "pick_model"):
            model = agent.pick_model(prompt)
        result = agent.run(task)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        # Agents may split their output into renderable sections (collapsible UI).
        sections = []
        if hasattr(agent, "build_sections"):
            sections = agent.build_sections(result, task.lang)
        if sections:
            # Clean fallback HTML for clients that ignore `sections`.
            result_html = "".join(
                (f"<h3>{s.title}</h3>{s.html}" if s.title else s.html)
                for s in sections
            )
        else:
            result_html = render_markdown(result)
        record = TaskRecord(
            status="completed",
            request=task,
            prompt=prompt,
            input_chars=len(prompt),
            model=model,
            result=result,
            result_html=result_html,
            sections=sections,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            duration_ms=duration_ms,
        )
        logger.info(
            "task completed agent=%s model=%s input=%.1fk duration_ms=%d chars=%d",
            task.agent,
            model,
            len(prompt) / 1000,
            duration_ms,
            len(result),
        )
    except Exception as exc:  # surface failures to the browser instead of a 500
        duration_ms = int((time.perf_counter() - t0) * 1000)
        record = TaskRecord(
            status="failed",
            request=task,
            prompt=prompt,
            input_chars=len(prompt),
            model=model,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            duration_ms=duration_ms,
            error=str(exc),
        )
        logger.exception(
            "task failed agent=%s input=%.1fk duration_ms=%d",
            task.agent,
            len(prompt) / 1000,
            duration_ms,
        )

    store.append(record)
    if record.status == "failed":
        raise HTTPException(status_code=502, detail=record.error)
    return record
