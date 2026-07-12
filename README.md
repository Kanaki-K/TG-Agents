# TG-Agents

**A personal, multi-agent AI content team ("content factory") for a Telegram channel and personal brand.**

Each agent is a separate Telegram bot running on a single shared *agent engine*. Memory is a separate, shared, inspectable layer — not hidden inside the agents. The system is designed core-first so it can be reused across products, not just Telegram.

<sub>Python · [aiogram](https://github.com/aiogram/aiogram) · [Claude API](https://docs.anthropic.com/) · Telegram MTProto (Telethon)</sub>

> **Status:** the content pipeline runs end-to-end (Scout → Creator → scheduled channel post). 5 bots + 1 "bot-less" role (Publisher). See [`docs/AUDIT.md`](docs/AUDIT.md) for the current maturity assessment and backlog.

---

## Table of contents

- [What it is](#what-it-is)
- [The team](#the-team)
- [How a post reaches the channel](#how-a-post-reaches-the-channel)
- [Architecture at a glance](#architecture-at-a-glance)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Design principles](#design-principles)
- [Documentation](#documentation)

---

## What it is

TG-Agents is a small fleet of role-specialised LLM agents that research, write, fact-check, illustrate, and schedule content for a Telegram channel — with the owner staying in the loop as the final approver.

The guiding idea is **"brains vs. hands"**: LLM reasoning is cheap and uniform, so it lives in one shared engine; the hard, fragile part is the *connectors* to the outside world (Telegram MTProto, RSS/web, X, image generation, market data). Core is deliberately decoupled from connectors so the same engine can power future agents and other products.

## The team

| Agent | Role | Entry point | Model |
|---|---|---|---|
| **Scout** | Trend & source recon (outbound), writes a research brief | `python run_scout.py` | Sonnet 4.6 |
| **Creator** | Writes posts, generates the cover, `/schedule` queues the post | `python run_creator.py` | Opus 4.8 |
| **Channel analyst** | Judges content by channel metrics (inbound) | `python run_analyst.py` | Haiku 4.5 |
| **Publisher** | Not a bot — the `/schedule` command inside Creator; a userbot posts the file into the channel's native *Scheduled* queue via MTProto | — | — |
| **Full pipeline** | Scout → Creator → scheduled post, in one command | `python run_pipeline.py` | — |

> The three content agents (Scout, Creator, Analyst) are the whole team. Earlier standalone bots — a personal assistant and a "developer" agent — were removed to keep the focus on the content factory; their code is recoverable from git history.

Each agent is defined by data in `agents/<name>/` (`config.yaml` + `SKILL.md` personality + `README.md`) and implemented by `core/<name>_bot.py` (+ `core/<name>_tools.py`). Adding an agent means filling in parameters — the engine is never touched.

## How a post reaches the channel

Steps are decoupled through a **file bus** (briefs and drafts on disk), so each stage can run independently; `run_pipeline.py` simply wires them into a single run.

```
SCOUT  /scan
  reads RSS + other Telegram channels + X leaders + web search + channel analytics (dedup)
  writes → memory/briefs/<date>-<slug>.md
        │
        ▼
DEDUP  (core/dedup — freshness gate + topic-repeat check before writing)
  refreshes stale channel data, compares brief angles against recent topics; all-repeat → stop
        │
        ▼
CREATOR  /post
  reads latest brief + 5 memory files + analytics ("what worked")
  draws the cover (make_image → ChatGPT burner → PNG)
  writes → memory/drafts/<date>-<slug>.md   (+ a code linter for formatting)
  auto 2FA fact-check (independent Sonnet pass with web search + live market price)
        │
        ▼
PUBLISHER  /schedule   (deterministic, no LLM, $0)
  picks the next content-plan slot, then a userbot places a native scheduled post
  (photo file + caption) into the channel and DMs the owner
        │
        ▼
  Owner reviews / edits / approves in the channel's native Scheduled queue.
```

Publishing is done **as a file** (photo + caption via MTProto), with no external image hosting or link previews — a deliberate, hard-won choice. `run_pipeline.py --skip-scout` reuses the latest brief; `--scope` runs a shorter analytical post format. See [`docs/scope.md`](docs/scope.md).

## Architecture at a glance

- **Brains vs. hands** — LLM logic runs in a generic engine (`core/agent_runtime.py`); the outside world is reached only through `connectors/`. Core is portable across products.
- **Dependency inversion** — `agent_runtime.run()` is fully parameterised (`tools_schema` / `dispatch` / `system_builder`). The engine knows nothing about specific agents; agents import the engine, never the reverse.
- **Data vs. judgement** — data reads go through a shared layer; agents exchange *judgement* through the file bus (briefs/drafts). Memory is a separate, ownerless, human-inspectable layer.

Full engineering map, fragility notes, and extension checklists are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Repository layout

```
core/          agent engine (agent_runtime, llm, config, tg_format, runmode, cost)
               + shared layers (memory, analytics, dedup, verify, content_plan)
               + per-agent code: <agent>_bot.py / <agent>_tools.py
agents/<name>/ agent definitions (data): config.yaml + SKILL.md personality + README.md
connectors/    "hands": Telegram MTProto (export/scan/publish), RSS/web, X, GPT image, source-media
               (og:image covers), market data, Threads API (Phase 2 — built, not yet wired to a bot)
memory/        shared layer: brand.md, post_standard.md, sources.md (canon); briefs/ & drafts/ (bus)
data/          runtime artefacts (git-ignored): sessions, exports, covers, cost log, run mode
docs/          PLAN.md (strategy), ARCHITECTURE.md (code map), AUDIT.md, scope.md
run_*.py       entry points (one per agent) + run_pipeline.py + run_cost_report.py
tests/         pytest suite
```

> **Why agent code lives in `core/`, not `agents/<name>/`:** agent folder names contain hyphens (e.g. `channel-analyst`), which are illegal in Python package names, so importable code follows the convention `core/<agent>_bot.py` + `core/<agent>_tools.py`, while `agents/<name>/` holds data only. See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for the rationale.

## Getting started

**Requirements:** Python 3.13 (see `.python-version`).

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   playwright install chromium   # for cover generation via web ChatGPT
   ```
   Exact pins are in `requirements.lock`; dev extras in `requirements-dev.txt`.

2. **Create the bots.** Register one bot per agent with [@BotFather](https://t.me/BotFather) and collect the tokens.

3. **Configure secrets:**
   ```bash
   cp .env.example .env
   ```
   Fill in the tokens and keys (see [Configuration](#configuration)).

4. **Run an agent** (see the table above) and message its bot in Telegram, or run the whole chain:
   ```bash
   python run_pipeline.py            # Scout → Creator → scheduled post
   python run_pipeline.py --skip-scout   # reuse the latest brief
   ```

5. **Track spend:**
   ```bash
   python run_cost_report.py         # token/cost report from data/cost_log.jsonl
   ```

## Configuration

All secrets live in `.env` (never committed; `.env.example` is the template). Key variables:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Shared Claude API key (per-agent overrides: `<AGENT>_ANTHROPIC_KEY`) |
| `SECRETARY_BOT_TOKEN`, `SCOUT_BOT_TOKEN`, `CREATOR_BOT_TOKEN`, `ANALYST_BOT_TOKEN`, `DEVELOPER_BOT_TOKEN` | Telegram bot tokens (one per agent) |
| `OWNER_ID` | Comma-separated Telegram user IDs allowed to use the bots (empty = open to everyone, with a loud startup warning; find yours via `/whoami`) |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_PHONE` | MTProto credentials for channel export, scanning, and publishing |
| `PUBLISH_CHANNEL` / `PUBLISH_NOTIFY` / `PUBLISH_TZ` | Publishing target, owner notifications, timezone |
| `COINMARKETCAP_API_KEY` | Live price/market-cap for fact-checking numbers |
| `X_AUTH_TOKEN` / `CT0` | Burner cookies for read-only X recon (Scout) |

**Run modes:** `/test` switches all bots to a cheap model (do not publish); `/main` switches to production. The mode is global via `data/run_mode.txt`.

## Design principles

- **Brains cheap, hands hard.** Keep LLM logic in the shared engine; invest care in connectors. Core stays decoupled so it's portable.
- **Memory is a shared external layer.** It can be opened and checked by hand.
- **Secrets only in `.env`.** Never in code or memory files.
- **Small, reviewable steps.** Every meaningful change is its own git commit; build from simple to complex.
- **Owner in the loop.** Nothing auto-publishes without review — the pipeline schedules, the owner approves.

## Documentation

- [`docs/PLAN.md`](docs/PLAN.md) — strategy, roadmap, and the "why"
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — engineering map: layers, data flow, fragility points, extension checklists
- [`docs/AUDIT.md`](docs/AUDIT.md) — maturity assessment and prioritised backlog
- [`docs/scope.md`](docs/scope.md) — the 🔭 short analytical post format
- [`CLAUDE.md`](CLAUDE.md) — working context for Claude Code
</content>
</invoke>
