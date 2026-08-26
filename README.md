# TG-Agents

**A personal, multi-agent AI content team ("content factory") for a Telegram channel and personal brand.**

Each agent is a separate Telegram bot running on a single shared *agent engine*. Memory is a separate, shared, inspectable layer — not hidden inside the agents. The system is designed core-first so it can be reused across products, not just Telegram.

<sub>Python · [aiogram](https://github.com/aiogram/aiogram) · [Claude API](https://docs.anthropic.com/) · Telegram MTProto (Telethon)</sub>

[![tests](https://github.com/Kanaki-K/TG-Agents/actions/workflows/tests.yml/badge.svg)](https://github.com/Kanaki-K/TG-Agents/actions/workflows/tests.yml)

> **Status — Phase 1 complete (Telegram: text + images); Phase 2 (Threads) well underway.** The content pipeline runs end-to-end (Scout → Creator → scheduled channel post) and is production-ready: **3 content agents** (Scout · Creator · Analyst) on one shared engine, a **self-learning topic loop** (live for Telegram), **240+ passing tests**, green CI with static linting (ruff), observable failure modes (silent degradation is logged, not hidden), one-command backup, and prompt-injection hardening. Maturity is tracked openly in [`docs/AUDIT.md`](docs/AUDIT.md) (8-axis, currently 7.2/10).
>
> **Roadmap:** ✅ **Phase 1** — Telegram (text + images) · 🚧 **Phase 2** — Threads: connector, analytics, and a **distillation content format** (TG flagship → native Threads series) are built, plus a **self-learning topic loop** (scores which *category* of topics resonates and gently tilts the flagship topic picker — **wired for Telegram** since 17.07, learning from on-channel performance; the Threads half is dormant until distillation data accrues). Remaining: delivery polish, a second native Threads format, auto-publish (posting is manual by design for now). · **Phase 3** — X/Twitter. See [`docs/AUDIT.md`](docs/AUDIT.md) for the maturity assessment and [`docs/PLAN.md`](docs/PLAN.md) for the roadmap.

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
| **Autopilot** | Not a bot — runs the flagship pipeline **on schedule** (its publish days, starting 4h before the slot) and reports to the owner in Telegram. Off by default; configured by chatting with Creator (`/autopilot`) | `python run_autopilot.py` | — |

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

### Autopilot: the same run, without a human trigger

Once the flagship format ran a month without a single owner edit, the missing piece was no longer quality
but **punctuality**. `run_autopilot.py` starts the *same* pipeline 4 hours before the publish slot, so the
post sits in the native *Scheduled* queue with a wide review window, and the owner gets a Telegram report
either way. The decision ("is it time?") is a pure function of time and on-disk state (`core/schedule.py`),
so it is unit-tested without spending money on real runs; the executor only obeys the verdict.

Two formats run on it **independently** — the long-form flagship (Tue/Thu) and the short news-driven
"scope" (Mon/Wed/Fri) — each with its own switch, schedule and "already ran today" mark, so a quiet week
on one is never a reason to ground the other. The scope format may legitimately produce nothing (its
freshness gate rejects stale news); the report says so explicitly rather than leaving silence to be
misread as a failure.

Gates are **in code, not in a prompt**: a per-format file switch (`data/autopilot_on_<format>`, absent by
default), a start *window* rather than an instant, "already ran today", "the slot is already taken", and a
hard stop in cheap-model test mode. The schedule itself is configured **by chatting with the Creator bot**
(`/autopilot`) — values arrive from a model, so ranges, a strict "which format?" parser and a "the window
can't be empty" cross-check are enforced by the validator, and every change is echoed back as
*before → after*. Full owner-facing guide: [`docs/AUTOPILOT.md`](docs/AUTOPILOT.md).

**Known limitations** (documented rather than hidden — all of them are consequences of running unattended):

| Limitation | Why it happens / what to expect |
|---|---|
| Owner's veto still consumes a bank topic | The topic is marked *used* when the post enters the queue, not when it publishes. Deleting the queued post keeps the topic out of rotation (~6 months). Fine at ~200 topics; needs a "return on veto" path if vetoing becomes common |
| Veto doesn't retract the published-flagships journal entry | That journal feeds the Threads distiller, so a vetoed post can still be distilled later. Visible while Threads is manual; must be wired before Threads is automated |
| A failed run still costs money | If it breaks after the writing stage, ~$1.4 is spent with no post, and there's no same-day retry (the "ran today" mark is set *before* the run, on purpose — otherwise a crash loop burns cash) |
| Chat control needs the bot alive | `/autopilot` works only while `run_creator.py` runs. The autopilot itself is independent; without the bot the panel is terminal-only (`--status`) |
| Host timezone ≠ channel timezone | The channel schedule is timezone-pinned (`PUBLISH_TZ`), but the OS scheduler fires on host local time. Travel moves the host clock, so the recipe uses a frequent alarm and lets the code decide — extra firings exit in milliseconds without touching the network |
| Cover generation is the fragile link | Covers come from a browser-automated ChatGPT burner profile. Expired session → the post ships **as text** with a warning in the report |
| No file log means no post-mortem | Background processes have nowhere to write stderr, so the autopilot mirrors its log to `data/autopilot.log` (`--log` tails it) and streams the pipeline narrative into it — otherwise a silent failure leaves no trace |

## Architecture at a glance

- **Brains vs. hands** — LLM logic runs in a generic engine (`core/agent_runtime.py`); the outside world is reached only through `connectors/`. Core is portable across products.
- **Dependency inversion** — `agent_runtime.run()` is fully parameterised (`tools_schema` / `dispatch` / `system_builder`). The engine knows nothing about specific agents; agents import the engine, never the reverse.
- **Data vs. judgement** — data reads go through a shared layer; agents exchange *judgement* through the file bus (briefs/drafts). Memory is a separate, ownerless, human-inspectable layer.

Full engineering map, fragility notes, and extension checklists are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Repository layout

```
core/          agent engine (agent_runtime, llm, config, tg_format, runmode, cost)
               + shared layers (memory, analytics, dedup, verify, content_plan)
               + self-learning topic loop (self_learn, category_scoring, topic_category, tg_scoring)
               + per-agent code: <agent>_bot.py / <agent>_tools.py
agents/<name>/ agent definitions (data): config.yaml + SKILL.md personality + README.md
connectors/    "hands": Telegram MTProto (export/scan/publish), RSS/web, X, GPT image, source-media
               (og:image covers), market data, Threads API (collect/insights/scoring/report/publish)
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

4. **Seed the recon source lists** (optional — Scout falls back to the shipped `*.example.yaml` templates if you skip this):
   ```bash
   cp connectors/telegram_scan/channels.example.yaml connectors/telegram_scan/channels.yaml
   cp connectors/x_scan/leaders.example.yaml          connectors/x_scan/leaders.yaml
   ```
   Fill in the channels / X handles you actually follow. The real lists are git-ignored (personal curation); only the templates are public.

5. **Run an agent** (see the table above) and message its bot in Telegram, or run the whole chain:
   ```bash
   python run_pipeline.py            # Scout → Creator → scheduled post
   python run_pipeline.py --skip-scout   # reuse the latest brief
   python run_autopilot.py --status  # what the scheduler thinks right now (no side effects)
   ```

6. **Track spend:**
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
| `PUBLISH_CHANNEL` / `PUBLISH_NOTIFY` / `PUBLISH_TZ` | Publishing target, owner notifications, timezone (an IANA name such as `Europe/Berlin`, so DST is handled) |
| `PUBLISH_FLAGSHIP_TIME` / `PUBLISH_SHORT_TIME` | Publish time per format, `HH:MM` in `PUBLISH_TZ`. Live edits made by chatting with Creator land in `data/plan_settings.json` and take precedence; `run_autopilot.py --status` prints which source won |
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
- [`docs/flagship.md`](docs/flagship.md) — the long educational post format (topic bank, voice anchors, run flow)
- [`docs/AUTOPILOT.md`](docs/AUTOPILOT.md) — scheduled autonomous runs: setup, safety gates, logs, known limitations
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — backups, "is the factory alive?", stop-cocks
- [`CLAUDE.md`](CLAUDE.md) — working context for Claude Code
</content>
</invoke>
