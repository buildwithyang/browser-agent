# Agent Bridge

English | [中文](README.zh-CN.md)

Turn a LinkedIn or Indeed job post into a tailored application.

> 📦 For installation, screenshots, and environment setup, see the [Chinese installation guide](deploy/INSTALL.zh-CN.md).

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

Agent Bridge combines a Chrome extension, a gateway, and AI agents. On a LinkedIn or Indeed job page, the user explicitly sends the visible job description to the agent.

```text
LinkedIn / Indeed job page
  ↓ right-click
Agent Bridge
  ↓
Job description + active CV
  ↓
Match analysis, tailored application content
  ↓
Result displayed on the current page
```

No copying and pasting. No switching between the job page and a chatbot. The user's current page becomes the context, and the agent turns it into action.

## Current Capabilities

- Capture the current job page's URL, title, selected text, and visible content.
- Compare a LinkedIn or Indeed job description with the user's active CV.
- Explain the company's business and the role's responsibilities.
- Produce a restrained match score grounded in core job requirements.
- Show matched, partial, and missing skills with evidence.
- Generate a job-specific Cover Letter on demand.
- Suggest concrete CV changes, including ATS keywords and achievement rewrites.
- Manage multiple CVs in a multi-tenant web application and choose the active CV.
- Display results directly inside the current page.

> Tailored CV generation, application tracking, and interview simulation are part of the product direction and are not yet complete end-to-end features.

## How It Works

1. Upload one or more CVs and select the active CV.
2. Open a job post on LinkedIn, Indeed, or another recruitment site.
3. Right-click and choose **Match against my resume**.
4. Review the conclusion, role overview, and skill-by-skill match.
5. If the role is worth pursuing, click **Write cover letter**.
6. Use the generated Cover Letter and CV recommendations to prepare the application.

The initial analysis is generated first. Cover Letter and CV recommendations are generated only when requested, which saves time and model usage for roles the user does not want to pursue.

## Product Principles

- **User-directed attention:** the user decides which page deserves AI assistance.
- **Workflow over chat:** results appear where the work is happening.
- **Truthful matching:** missing core requirements must lower the score; the agent should not give comfort scores.
- **User data isolation:** CVs and application data are scoped to the signed-in user.
- **Privacy by default:** page content, CV text, and full prompts are sensitive; long-term storage should favor operational metrics over raw content.
- **Vendor-neutral models:** the gateway supports OpenAI-compatible model endpoints and prompt-length routing.

## Architecture

```text
Chrome Extension
  ↓
FastAPI Gateway
  ├─ Auth and session
  ├─ CV management
  ├─ Task orchestration
  └─ Job-match agent
       ↓
OpenAI-compatible model
```

The cloud architecture is designed for multiple users. The gateway keeps API, service, repository, and database responsibilities separated, while the job agents remain stateless and receive user-specific CV data for each request.

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
- On-demand Cover Letter and CV improvement suggestions

### Next — Apply

- Generate a tailored CV from verified user experience
- Save jobs and application records
- Keep generated CV and Cover Letter versions together

### Later — Win the Offer

- Interview questions based on the JD and the user's CV
- Mock interviews and feedback
- Follow-up and application-stage assistance

The long-term vision remains broader: any browser page can become an AI task. Job seeking is the first complete workflow through which Agent Bridge will prove that vision.
