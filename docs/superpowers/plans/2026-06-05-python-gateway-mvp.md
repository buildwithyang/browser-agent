# Python Gateway MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working Agent Bridge loop: a Chrome extension sends page context to a local Python gateway, a built-in **simple-agent** (backed by Claude directly) analyzes it, and **the result is returned to the browser and shown to the user** — all without requiring the user to install any external agent (Claude Code, Codex, etc.).

**Architecture:** The browser extension owns page capture, the explicit user action, and result display. The Python gateway owns local HTTP intake, agent dispatch, prompt construction, synchronous result return, and task persistence. The MVP implements only the built-in `SimpleAgent` (calls the Claude Messages API directly), but keeps the `AgentAdapter` interface ready for future external adapters (Claude Code, Codex, OpenClaw).

**Why a built-in agent first:** The original plan assumed an external Codex CLI. That forces every user to install and configure a separate agent before Agent Bridge does anything. The built-in `SimpleAgent` needs only an `OPENAI_API_KEY` env var, so the product works out of the box. External adapters become an opt-in upgrade later, not a prerequisite.

**Tech Stack:** Chrome Extension Manifest V3, Python 3.11+, FastAPI, Pydantic, uvicorn, the official `openai` SDK, pytest, JSONL task storage.

**LLM backend:** OpenAI via the official `openai` SDK, using the Chat Completions API. We use the OpenAI-compatible interface deliberately so the backend can be swapped at any time — point it at OpenAI, a local model, or any OpenAI-compatible gateway by setting `OPENAI_BASE_URL`. Configuration is all env-var driven: `OPENAI_API_KEY` (required), `OPENAI_BASE_URL` (optional, defaults to OpenAI), and `AGENT_BRIDGE_MODEL` (model id, default `gpt-4o-mini`).

---

## File Structure

- `extension/manifest.json`: Chrome extension manifest with context menu, active tab, scripting, and notifications permissions.
- `extension/background.js`: Creates the context menu, posts captured context to the gateway, and renders the returned result into the page.
- `extension/content.js`: Extracts selected text and readable page text from the current page.
- `gateway/pyproject.toml`: Python package metadata and dependencies.
- `gateway/app/main.py`: FastAPI app and HTTP routes (returns the agent result synchronously).
- `gateway/app/models.py`: Pydantic request and task models.
- `gateway/app/agents/base.py`: Shared adapter interface.
- `gateway/app/agents/simple.py`: Built-in agent — prompt builder + OpenAI Chat Completions call.
- `gateway/app/storage/tasks.py`: JSONL task persistence.
- `gateway/tests/test_simple_agent.py`: Prompt formatting + `run()` tests (Claude client faked).
- `gateway/tests/test_tasks_api.py`: API behavior tests (agent faked).
- `README.md`: Add local setup and MVP usage instructions.

---

### Task 1: Gateway Models And Built-in Simple Agent

**Files:**
- Create: `gateway/pyproject.toml`
- Create: `gateway/app/__init__.py`
- Create: `gateway/app/models.py`
- Create: `gateway/app/agents/__init__.py`
- Create: `gateway/app/agents/base.py`
- Create: `gateway/app/agents/simple.py`
- Create: `gateway/tests/test_simple_agent.py`

- [ ] **Step 1: Add Python project metadata**

Create `gateway/pyproject.toml`:

```toml
[project]
name = "agent-bridge-gateway"
version = "0.1.0"
description = "Local gateway for sending browser context to a built-in Claude agent."
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.111.0",
  "pydantic>=2.7.0",
  "uvicorn>=0.30.0",
  "openai>=1.40.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2.0",
  "httpx>=0.27.0",
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

> Note: any `openai` SDK in the 1.x line exposes `client.chat.completions.create(...)` and the `base_url` constructor argument, so the exact floor is not critical. The model id is just a string passed through to whatever endpoint `OPENAI_BASE_URL` points at.

- [ ] **Step 2: Write simple-agent tests**

Create `gateway/tests/test_simple_agent.py`:

```python
from types import SimpleNamespace

from app.agents.simple import SimpleAgent
from app.models import BrowserContext, TaskCreate


def make_task() -> TaskCreate:
    return TaskCreate(
        intent="Analyze this job for resume fit.",
        context=BrowserContext(
            url="https://example.com/jobs/123",
            title="Senior Golang Engineer",
            selected_text="Dubai remote role",
            page_text="We need Go, Kubernetes, and backend experience.",
        ),
    )


def test_prompt_contains_browser_context():
    prompt = SimpleAgent().build_prompt(make_task())

    assert "Analyze this job for resume fit." in prompt
    assert "https://example.com/jobs/123" in prompt
    assert "Senior Golang Engineer" in prompt
    assert "Dubai remote role" in prompt
    assert "We need Go, Kubernetes" in prompt


def test_run_returns_model_text_and_passes_model():
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Here are the next steps.")
                )
            ]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    agent = SimpleAgent(client=fake_client, model="gpt-4o-mini")
    result = agent.run(make_task())

    assert result == "Here are the next steps."
    assert captured["model"] == "gpt-4o-mini"
    # The page context must reach the model via the user message (index 1; the
    # system prompt is index 0).
    user_text = captured["messages"][1]["content"]
    assert "Senior Golang Engineer" in user_text
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
cd gateway
uv run pytest tests/test_simple_agent.py -v
```

Expected: FAIL because `app.agents.simple` does not exist.

- [ ] **Step 4: Add models and adapter interface**

Create `gateway/app/__init__.py`:

```python
```

Create `gateway/app/models.py`:

```python
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# "simple" is the built-in Claude-backed agent. The others are reserved for
# future external adapters and are not implemented in the MVP.
AgentName = Literal["simple", "claude-code", "codex", "openclaw"]


class BrowserContext(BaseModel):
    url: str
    title: str
    selected_text: str = ""
    page_text: str = ""


class TaskCreate(BaseModel):
    intent: str = "Analyze this page and propose next steps."
    agent: AgentName = "simple"
    context: BrowserContext


class TaskRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["created", "completed", "failed"] = "created"
    request: TaskCreate
    prompt: str
    result: str = ""
    error: str = ""
```

Create `gateway/app/agents/__init__.py`:

```python
```

Create `gateway/app/agents/base.py`:

```python
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
```

- [ ] **Step 5: Add the built-in SimpleAgent**

Create `gateway/app/agents/simple.py`:

```python
import os

from openai import OpenAI

from app.agents.base import AgentAdapter
from app.models import TaskCreate

SYSTEM_PROMPT = (
    "You are Agent Bridge, a helpful assistant that receives the content a user "
    "is currently viewing in their browser. Analyze the provided page context "
    "against the user's intent and respond with concrete, actionable next steps. "
    "Be concise and structured."
)

DEFAULT_MODEL = os.environ.get("AGENT_BRIDGE_MODEL", "gpt-4o-mini")


class SimpleAgent(AgentAdapter):
    name = "simple"

    def __init__(self, client: OpenAI | None = None, model: str | None = None) -> None:
        self._client = client
        self.model = model or DEFAULT_MODEL

    @property
    def client(self) -> OpenAI:
        # Lazily construct so importing this module never requires an API key.
        # OpenAI() reads OPENAI_API_KEY and (optionally) OPENAI_BASE_URL from the
        # environment, so any OpenAI-compatible endpoint can be swapped in without
        # code changes.
        if self._client is None:
            self._client = OpenAI()
        return self._client

    def build_prompt(self, task: TaskCreate) -> str:
        context = task.context
        return "\n".join(
            [
                "User intent:",
                task.intent.strip(),
                "",
                "Page URL:",
                context.url,
                "",
                "Page title:",
                context.title,
                "",
                "Selected text:",
                context.selected_text.strip() or "(none)",
                "",
                "Page text:",
                context.page_text.strip() or "(none)",
            ]
        )

    def run(self, task: TaskCreate) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self.build_prompt(task)},
            ],
        )
        return response.choices[0].message.content or ""
```

- [ ] **Step 6: Run tests to verify they pass**

Run:

```bash
cd gateway
uv run pytest tests/test_simple_agent.py -v
```

Expected: PASS.

---

### Task 2: Task API That Returns The Result + JSONL Storage

**Files:**
- Create: `gateway/app/storage/__init__.py`
- Create: `gateway/app/storage/tasks.py`
- Create: `gateway/app/main.py`
- Create: `gateway/tests/test_tasks_api.py`

- [ ] **Step 1: Write task API test**

The agent is faked so the test never calls the real Claude API, and the store is pointed at a temp path so the test does not write into the repo.

Create `gateway/tests/test_tasks_api.py`:

```python
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.storage.tasks import JsonlTaskStore


def test_create_task_returns_result(tmp_path, monkeypatch):
    fake_agent = SimpleNamespace(
        build_prompt=lambda task: "PROMPT",
        run=lambda task: "Summary: this page is about Go jobs.",
    )
    monkeypatch.setitem(main.agents, "simple", fake_agent)
    monkeypatch.setattr(main, "store", JsonlTaskStore(tmp_path / "tasks.jsonl"))

    client = TestClient(main.app)
    response = client.post(
        "/tasks",
        json={
            "intent": "Summarize this page.",
            "agent": "simple",
            "context": {
                "url": "https://example.com/article",
                "title": "Example Article",
                "selected_text": "important section",
                "page_text": "full article text",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request"]["agent"] == "simple"
    assert body["status"] == "completed"
    assert body["result"] == "Summary: this page is about Go jobs."


def test_unsupported_agent_returns_400(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", JsonlTaskStore(tmp_path / "tasks.jsonl"))
    client = TestClient(main.app)
    response = client.post(
        "/tasks",
        json={
            "agent": "codex",
            "context": {"url": "https://example.com", "title": "x"},
        },
    )
    assert response.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd gateway
uv run pytest tests/test_tasks_api.py -v
```

Expected: FAIL because `app.main` does not exist.

- [ ] **Step 3: Add JSONL task store**

Create `gateway/app/storage/__init__.py`:

```python
```

Create `gateway/app/storage/tasks.py`:

```python
from pathlib import Path

from app.models import TaskRecord


class JsonlTaskStore:
    def __init__(self, path: Path | str = "data/tasks.jsonl") -> None:
        self.path = Path(path)

    def append(self, task: TaskRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(task.model_dump_json() + "\n")
```

- [ ] **Step 4: Add FastAPI route that runs the agent and returns the result**

Create `gateway/app/main.py`:

```python
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agents.simple import SimpleAgent
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
    "simple": SimpleAgent(),
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
```

- [ ] **Step 5: Run API tests**

Run:

```bash
cd gateway
uv run pytest -v
```

Expected: PASS (both test files).

---

### Task 3: Chrome Extension MVP (capture → send → show result)

**Files:**
- Create: `extension/manifest.json`
- Create: `extension/content.js`
- Create: `extension/background.js`

- [ ] **Step 1: Create extension manifest**

Create `extension/manifest.json`:

```json
{
  "manifest_version": 3,
  "name": "Agent Bridge",
  "version": "0.1.0",
  "description": "Send the current webpage context to a local agent and see the result in the page.",
  "permissions": ["contextMenus", "activeTab", "scripting", "notifications"],
  "host_permissions": ["http://127.0.0.1:17321/*"],
  "background": {
    "service_worker": "background.js"
  }
}
```

- [ ] **Step 2: Add page extraction script**

Create `extension/content.js`:

```javascript
function getPageText() {
  return document.body.innerText.replace(/\s+/g, " ").trim().slice(0, 20000);
}

chrome.runtime.sendMessage({
  type: "AGENT_BRIDGE_CONTEXT",
  payload: {
    url: window.location.href,
    title: document.title,
    selected_text: window.getSelection().toString(),
    page_text: getPageText()
  }
});
```

- [ ] **Step 3: Add context menu, gateway POST, and result rendering**

Create `extension/background.js`:

```javascript
const GATEWAY_URL = "http://127.0.0.1:17321/tasks";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "send-to-agent-bridge",
    title: "Send to Agent Bridge",
    contexts: ["page", "selection"]
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "send-to-agent-bridge" || !tab.id) {
    return;
  }
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["content.js"]
  });
});

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message.type !== "AGENT_BRIDGE_CONTEXT" || !sender.tab) {
    return;
  }
  const tabId = sender.tab.id;

  fetch(GATEWAY_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      intent: "Analyze this page and propose next steps.",
      agent: "simple",
      context: message.payload
    })
  })
    .then((response) => response.json())
    .then((task) => showResult(tabId, task.result || "(no result)"))
    .catch((error) => {
      console.error("Agent Bridge gateway request failed", error);
      showResult(tabId, "Agent Bridge error: " + error.message);
    });
});

// Render the result in an overlay panel injected into the originating page.
function showResult(tabId, text) {
  chrome.scripting.executeScript({
    target: { tabId },
    func: renderPanel,
    args: [text]
  });
}

function renderPanel(text) {
  const existing = document.getElementById("agent-bridge-panel");
  if (existing) existing.remove();

  const panel = document.createElement("div");
  panel.id = "agent-bridge-panel";
  panel.style.cssText = [
    "position:fixed", "top:16px", "right:16px", "z-index:2147483647",
    "max-width:420px", "max-height:70vh", "overflow:auto",
    "background:#1e1e1e", "color:#f0f0f0", "padding:16px",
    "border-radius:8px", "box-shadow:0 4px 24px rgba(0,0,0,0.4)",
    "font:14px/1.5 system-ui,sans-serif", "white-space:pre-wrap"
  ].join(";");

  const close = document.createElement("button");
  close.textContent = "×";
  close.style.cssText = "float:right;background:none;border:none;color:#f0f0f0;font-size:20px;cursor:pointer";
  close.onclick = () => panel.remove();

  const body = document.createElement("div");
  body.textContent = text;

  panel.appendChild(close);
  panel.appendChild(body);
  document.body.appendChild(panel);
}
```

- [ ] **Step 4: Manually test the full loop**

Set the API key and run the gateway:

```bash
cd gateway
export OPENAI_API_KEY=sk-...
# optional: point at a non-OpenAI, OpenAI-compatible endpoint
# export OPENAI_BASE_URL=http://localhost:11434/v1
# export AGENT_BRIDGE_MODEL=gpt-4o-mini
uv run uvicorn app.main:app --host 127.0.0.1 --port 17321
```

Expected: server starts and `GET http://127.0.0.1:17321/health` returns `{"status":"ok"}`.

Load `extension/` in Chrome as an unpacked extension, open any page, optionally select text, right click, choose `Send to Agent Bridge`.

Expected: a dark overlay panel appears in the top-right of the page containing the agent's analysis, and `gateway/data/tasks.jsonl` contains one task with status `completed`, the prompt, and the result.

---

### Task 4: README Setup Notes

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add MVP usage section**

Append this section to `README.md`:

```markdown
## Local MVP

The first implementation uses:

* Chrome Extension for explicit page capture and in-page result display
* Python FastAPI gateway on `127.0.0.1:17321`
* A built-in `SimpleAgent` backed by an OpenAI-compatible model (no external agent install required)
* JSONL task storage at `gateway/data/tasks.jsonl`

Set your API key and run the gateway:

```bash
cd gateway
export OPENAI_API_KEY=sk-...
uv run uvicorn app.main:app --host 127.0.0.1 --port 17321
```

Backend is fully swappable via environment variables:

* `OPENAI_API_KEY` — API key (required)
* `OPENAI_BASE_URL` — point at any OpenAI-compatible endpoint (OpenAI default; e.g. a local model or proxy)
* `AGENT_BRIDGE_MODEL` — model id (default `gpt-4o-mini`)

Load the Chrome extension:

1. Open `chrome://extensions`
2. Enable Developer Mode
3. Click `Load unpacked`
4. Select the `extension/` directory

Use it:

1. Open a webpage
2. Select text if needed
3. Right click
4. Choose `Send to Agent Bridge`
5. Read the result in the overlay panel that appears in the page
```

- [ ] **Step 2: Verify README remains readable**

Open `README.md` and confirm it has the original product overview plus the new Local MVP section.

---

## Self-Review

- Spec coverage: covers browser capture, gateway intake, built-in LLM analysis, **synchronous result return to the browser**, in-page result display, JSONL persistence, and adapter boundaries for future external agents.
- Goal alignment: (1) the agent returns a result that the extension renders in the page; (2) the built-in `SimpleAgent` is the only implemented agent and needs only an API key — no Claude Code / Codex install. Using the OpenAI-compatible SDK keeps the backend swappable (OpenAI, local models, or any compatible gateway via `OPENAI_BASE_URL`).
- Placeholder scan: no TBD/TODO/fill-in steps remain.
- Type consistency: `BrowserContext`, `TaskCreate`, `TaskRecord`, `AgentAdapter.build_prompt()/run()`, and `SimpleAgent` are defined before use.
- Testability: both the Claude client and the agent are injectable/faked, so the test suite runs without an API key or network access.
- Scope control: streaming, auth, multi-task history UI, and external adapters are intentionally deferred until the first browser-to-result loop works.
```
