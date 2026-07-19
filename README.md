# Agent Bridge

English | [中文](README.zh-CN.md)

Turn a LinkedIn or Indeed job post into a tailored application.

> 📦 For installation, screenshots, and environment setup, see the [Chinese installation guide](deploy/INSTALL.zh-CN.md).

> The Shared Workspace described below is implemented in the current source tree. Cloud gateway deployment and Chrome Web Store publication are separate release steps.

## Vision

**Respect the user's attention and make AI part of the workflow.**

For a long time, people will still use the browser to discover and understand information. When a user reads an article, reviews a job post, checks a GitHub issue, or opens an email, Agent Bridge should understand what currently has their attention and help immediately.

AI should do more than answer questions. It should apply computing power directly where the user is already focused.

## Mission

**Start with one small, real need: help people understand and match job descriptions.**

Agent Bridge is not trying to become a universal agent on day one. The first goal is to complete one workflow that job seekers repeat every day:

```text
Right-click a LinkedIn / Indeed job post
  ↓
Analyze the role and CV match
  ↓
Tailor the CV
  ↓
Generate a Cover Letter
  ↓
Track the application
  ↓
Prepare for interviews
  ↓
Offer
```

The near-term goal is simple: help the user get their first offer. Once this workflow works end to end, Agent Bridge can expand to other browser-based scenarios.

## What Agent Bridge Does

Agent Bridge combines a Chrome extension, a gateway, and AI agents. The browser first shows a focused **Quick Insight**; an Action then opens a persistent Side Panel where the user can finish the task without repeating the page context.

```text
LinkedIn / Indeed job page
  ↓ right-click
Quick Insight
  ↓ choose an Action
Shared Workspace in the Side Panel
  ↓
Current page + active CV + shared history
  ↓
Analysis, tailored resume, or Cover Letter
```

No copying and pasting. No switching between the job page and a separate chatbot. The user's current page becomes the context, and the agent turns it into action.

## Current Capabilities

- Show a Quick Insight for any webpage; LinkedIn and Indeed receive job-match insight when a complete JD is selected, while other pages receive a summary.
- Compare a LinkedIn or Indeed job description with the user's active CV and explain the business, role focus, strongest match, and largest gap.
- Offer four job Actions: **Analyze**, **Tailor Resume**, **Generate Cover Letter**, and **Ask More**. General webpages offer **Ask More**.
- Open every Action for the same page in one Side Panel Workspace, with one chronological history and an optional generated document.
- Preserve that Workspace locally for the same signed-in user and normalized webpage resource.
- Continue refining a resume or Cover Letter from the shared context instead of starting a new chat.
- Manage multiple CVs in a multi-tenant web application and choose the active CV.
- Keep Context Routing and webpage-resource normalization in the gateway, so supported sites can evolve without republishing the extension.

Workspace history is stored in the current Chrome profile, not as a server-side conversation. Existing history plus the current user message may not exceed ten entries; the final assistant reply is still kept, so the completed local timeline can contain eleven messages.

## How It Works

1. Upload one or more CVs and select the active CV.
2. Open a page. For LinkedIn or Indeed job matching, select the complete JD.
3. Right-click and choose **Browser Agent**.
4. Read the Quick Insight and choose the next Action.
5. Continue in the Side Panel. Switching Actions changes how the next message is handled; it does not clear the shared history.
6. Copy the latest tailored resume or Cover Letter when it is ready.

Quick Insight answers “What should I know?” first. The Workspace then answers “What should I do next?” without forcing the user to begin with a blank chat box.

## Product Principles

- **User-directed attention:** the user decides which page deserves AI assistance.
- **Workflow over chat:** results appear where the work is happening.
- **One resource, one Workspace:** Actions share one local history for the signed-in user and normalized webpage.
- **Truthful matching:** missing core requirements must lower the score; the agent should not give comfort scores.
- **User data isolation:** CVs and application data are scoped to the signed-in user.
- **Explicit data handling:** page content, CV text, and full prompts are sensitive. The current internal-user phase persists task details for debugging; a public production rollout must define redaction, access, and retention controls.
- **Vendor-neutral models:** the gateway supports OpenAI-compatible model endpoints and prompt-length routing.

## Architecture

```text
Chrome Extension
  ├─ Quick Insight overlay
  ├─ Side Panel Workspace
  └─ owner + resource scoped local state
       ↓
FastAPI Gateway
  ├─ Auth and session
  ├─ CV management
  ├─ Context Router + resource normalization
  ├─ Stateless task orchestration
  └─ Job-match / page-summary agents
       ↓
OpenAI-compatible model
```

The cloud architecture is designed for multiple users. The gateway keeps API, service, repository, and database responsibilities separated, while agents remain stateless and receive page context, shared history, and user-specific CV data with each request. The public Quick Insight and Workspace APIs do not expose an Agent selector; routing is a backend responsibility.

## Local Development

Requirements and detailed setup are documented in the [installation guide](deploy/INSTALL.zh-CN.md).

Start the gateway:

```bash
cd gateway
cp .env.example .env
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 17321
```

The model backend is configured through `AGENT_BRIDGE_MODELS`, a JSON map that routes requests by prompt length. The minimal configuration needs only a `default` model. See [gateway/.env.example](gateway/.env.example).

Install the extension from the [Chrome Web Store](https://chromewebstore.google.com/detail/agent-bridge/cmajoaedbjinocbfdkebaedkdbkhbhai), or load `extension/` from `chrome://extensions` in Developer Mode.

Run the gateway tests:

```bash
cd gateway
uv run pytest
```

Run the extension tests:

```bash
cd extension
npm test
```

## Roadmap

### Now — Understand and Match

- LinkedIn / Indeed job-page capture
- CV-to-JD match analysis
- Role and company overview
- Skill gaps and realistic scoring
- Shared Side Panel history across Actions
- On-demand tailored resume and Cover Letter drafts

### Next — Apply

- Export and version tailored CVs from verified user experience
- Save jobs and application records
- Keep generated CV and Cover Letter versions together

### Later — Win the Offer

- Interview questions based on the JD and the user's CV
- Mock interviews and feedback
- Follow-up and application-stage assistance

The long-term vision remains broader: any browser page can become an AI task. Job seeking is the first complete workflow through which Agent Bridge will prove that vision.
