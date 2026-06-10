Agent Bridge

Turn any webpage into actionable AI context.

Overview

Agent Bridge is a browser extension and local gateway that allows users to send the content they are currently viewing to a local AI agent.

The goal is simple:

Read
  ↓
Send To Agent
  ↓
Get Result

Without:

Copy
Paste
Switch Window
Repeat Context
Problem

Today users constantly move information between:

LinkedIn
GitHub
Jira
Notion
Technical Documentation
ChatGPT
Claude

Typical workflow:

Read content
    ↓
Copy
    ↓
Open ChatGPT
    ↓
Paste
    ↓
Ask question

Or:

Read content
    ↓
Copy
    ↓
Open terminal
    ↓
Paste
    ↓
Execute

The work is repetitive and inefficient.

Solution

Agent Bridge lets users explicitly send browser context to an AI agent.

Browser
    ↓
Agent Bridge
    ↓
Local Gateway
    ↓
Agent
    ↓
Result
    ↓
Browser

The browser becomes the source of context.

The agent becomes the processor.

Core Principle

Agent Bridge is NOT browser automation.

Agent Bridge is NOT a Playwright replacement.

Agent Bridge is a context delivery system.

The user decides:

This content matters.
Send it to the agent.

This explicit signal is more valuable than continuously monitoring webpages.

Use Cases
LinkedIn Job Analysis

Current page:

Senior Golang Engineer
Remote
Dubai

User:

Right Click
↓
Send To Agent

Agent returns:

Job summary
Resume match score
Potential risks
Interview preparation notes
Suggested salary range
GitHub Issue Analysis

Current page:

Fix OpenIM login timeout issue

User:

Send To Agent

Agent returns:

Problem summary
Possible root causes
Suggested implementation approach
Technical Documentation

Current page:

Quectel 5G License Guide

User:

Send To Agent

Agent returns:

Key implementation steps
Risks
Suggested development tasks
ChatGPT / Claude Conversation

Current page contains an AI-generated plan.

User:

Send To Agent

Agent returns:

Critical review
Missing considerations
Improvement suggestions
MVP Scope
Browser Extension

Collect:

URL
Page Title
Selected Text
Visible Page Content

Actions:

Send To Agent
Local Gateway

Receive browser context.

Expose:

POST /analyze

Request:

{
  "url": "...",
  "title": "...",
  "selection": "...",
  "content": "..."
}
Internal Agent

MVP uses a built-in LLM backend.

Responsibilities:

Analyze
Summarize
Extract
Generate
Execute cmd
Future Roadmap
Phase 1
Browser
    ↓
Internal Agent
    ↓
Result Popup

Validate demand.

Phase 2
Browser
    ↓
Gateway
    ↓
Agent
    ↓
Result
    ↓
Current Webpage

Allow results to be inserted into:

ChatGPT
Claude
LinkedIn Messages
Jira Comments
Any Web Input
Vision

Any webpage can become an AI task.

Any Webpage
    ↓
Send To Agent
    ↓
Analyze
    ↓
Return Result

No copy-paste.

No context switching.

Just context → action.

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

The backend is fully swappable via environment variables:

* `OPENAI_API_KEY` — API key (required)
* `OPENAI_BASE_URL` — point at any OpenAI-compatible endpoint (defaults to OpenAI; e.g. a local model or proxy)
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

Run the gateway tests:

```bash
cd gateway
uv run pytest
```
