# memory/ — shared memory layer

This is the shared, human-inspectable memory layer of the agent fleet (see [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) §6 for who reads/writes each file).

> **The actual content of this folder is intentionally kept out of the public repository.**
> It holds the brand playbook, voice standard, content lessons, and the owner's personal
> profile and to-do — private material, not code. In this public repo only this README and the
> folder structure are versioned; everything else is git-ignored (`.gitignore`).
>
> The content **is** versioned — in a **separate private repo** (`tg-agents-memory`, a nested
> `.git` inside this folder) for backup + history, decoupled from the public code repo. The
> runtime never reads from GitHub — it reads these files from disk; git is backup only.
> Operational manual for that private repo: `MEMORY_REPO.md` (itself private).

## What lives here (created/maintained at runtime, not in git)

| File | Purpose | Written by |
|---|---|---|
| `brand.md` | Brand canon: niche, voice, value lens | owner |
| `content_manual.md` | The flagship "bible" — richest writing input | owner |
| `voice_core.md` | Voice / anti-AI / typography canon — **loaded ONLY by scope** (flagship has its own copy in `content_manual §5/§7`) | owner |
| `headline_bank.md` | Approved channel headlines — taste reference, **scope-only** | scope (from `channel_posts.json`) |
| `post_standard.md` | Post standard + formats | Creator (`apply_standard`) |
| `post_lessons.md` | Lessons learned from owner edits | Creator (`record_lesson`) |
| `scope_manual.md` / `scope_lessons.md` | Rules & lessons for the 🔭 short format | owner / scope branch |
| `flagship_topics.md` | Evergreen topic bank | owner |
| `image_prompt.md` | Cover-image style prompt | owner |
| `sources.md` | Scout source list | owner / Scout |
| `profile.md` | Owner profile (personal assistant canon) | Personal assistant |
| `tasks.json` / `tasks.md` | The owner's "living to-do" | Personal assistant |
| `journal/` | Session summaries & decisions | Personal assistant |
| `briefs/` · `drafts/` | Pipeline file-bus (research briefs, post drafts) | Scout / Creator |

To run the fleet, populate these files with your own brand canon and let the agents maintain the rest.
</content>
