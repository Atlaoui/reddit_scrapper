# Project History & Technical Decisions

## What This Project Does

`reddit-avatar` turns a free-text research demand into a structured set of customer avatar profiles, grounded entirely in real Reddit discussions. You type something like _"I want to understand people building their first homelab"_ and get back a Markdown report with 1–4 richly detailed archetypes — their pains, desires, vocabulary, jobs-to-be-done, and worldview — each claim citing the exact Reddit post it came from.

---

## How It Started

The original version was config-driven: you hand-wrote a YAML file listing subreddits and search queries, then ran the pipeline. This required knowing Reddit communities in advance, which defeated the point for exploratory research.

**Original flow:**
```
YAML config → harvest → extract → cluster → synthesize → render
```

---

## What Was Changed

### 1. LLM-powered subreddit discovery (`discover` command)

Added a new entry point: `reddit-avatar discover "<demand>"`. The user provides a free-text research intent and an LLM automatically recommends 4–8 relevant subreddits and a topic label. This replaces the need to know Reddit communities in advance.

New files:
- `prompts/suggest_subreddits.md` — prompt instructing the LLM to return `{topic, subreddits, search_queries}` JSON
- `src/reddit_avatar/suggest.py` — calls the LLM, validates the response into a `SuggestionResult`

The `discover` command builds a `TopicConfig` from the suggestions and calls the same pipeline as `run`.

---

### 2. Switched from Anthropic SDK to Ollama (local LLM)

The project originally used Anthropic's API (`claude-haiku` for extraction, `claude-opus` for clustering/synthesis). This was replaced with a local Ollama instance using the OpenAI-compatible API (`http://localhost:11434/v1`).

**Why:** free to run locally, no API key required, works offline.

**`llm.py` changes:**
- Replaced `anthropic.Anthropic` client with `openai.OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")`
- Kept the same `call_json(model, system, user)` interface so `extract.py`, `cluster.py`, `synthesize.py` needed zero changes
- `HAIKU` and `OPUS` constants now both point to the configured Ollama model (default: `gemma3`)
- Cost tracking kept but always returns $0.00 for local models

**Model tried:** `gemma3` (default). Can be overridden with `OLLAMA_MODEL` env var.

---

### 3. Reddit scraping without a Reddit app

This was the most iterative part. Reddit blocks unauthenticated bots.

**Attempts made (in order):**

| Attempt | Result |
|---------|--------|
| Custom User-Agent `reddit-avatar/0.1` | 403 on all requests |
| Browser User-Agent via `httpx` | Works for some posts, 403 on `/search.json` and some individual posts |
| Reddit OAuth (client credentials) | Works but requires registering an app — rejected to keep setup simple |
| Selenium headless Chrome | Works — Reddit serves JSON to real browsers |

**Final approach:** Selenium with headless Chrome via `webdriver-manager` (auto-downloads the right ChromeDriver). Navigate directly to `.json` URLs — Reddit returns raw JSON in the browser.

**Why search was dropped:** `/search.json` requires OAuth regardless of how the request is made. Instead, the pipeline fetches `/top.json` from each subreddit. Since the LLM already picks targeted communities, top posts are sufficient.

**`harvest.py` changes:**
- Replaced `httpx.Client` with a Selenium `webdriver.Chrome` instance
- `_fetch()` navigates to the URL, reads `body.text`, parses JSON
- 403 responses (login-gated posts) are silently skipped — no retry
- 3-second delay between requests to avoid 429s
- Disk cache (SHA256 of URL) preserved — re-runs don't re-fetch

---

### 4. Per-stage caching and run resumption

Originally, every run created a new `run_id` and re-ran all LLM stages from scratch even if the same topic had been processed before.

**Added:**
- `store.find_run(config_hash)` — finds an existing non-errored run with the same config hash
- `runs.cluster_json` column — stores cluster result so it's not re-computed
- `store.get_cluster(run_id)` / `store.save_cluster(run_id, json)`
- `store.get_avatars(run_id)` — checks if synthesis already completed
- Schema migration on startup via `PRAGMA table_info(runs)` + `ALTER TABLE ADD COLUMN`

**Cache map:**

| Stage | Cache |
|-------|-------|
| HTTP responses | `data/cache/{sha256}.json` on disk |
| Signal extraction | SQLite `signals` table, keyed by `(post_id, prompt_version)` |
| Cluster result | SQLite `runs.cluster_json` column |
| Avatar synthesis | SQLite `avatars` table |
| Run identity | SQLite `runs` table, matched by `config_hash` |

Re-running the exact same demand prints `Resuming run N` and skips straight to rendering.

---

### 5. Local LLM reliability fixes

Gemma3 (and small local models generally) don't reliably follow JSON output instructions.

**Problems encountered:**
- `jtbd` returned as a string instead of a list → Pydantic validation error → signal extraction fails → nothing to cluster
- Model returns `{}` when `response_format={"type":"json_object"}` is set → pipeline crashes at synthesis
- Model returns prose paragraphs instead of JSON

**Fixes:**

**`schemas.py`** — added a `_coerce_to_list` validator on all list fields in `ExtractedSignals` and `AvatarProfile`. If the model returns a string, it gets wrapped in a list automatically.

**`llm.py`** — 3-attempt retry loop:
1. First attempt: normal call
2. If JSON parse fails or returns `{}`: send the bad response back and ask explicitly for JSON only
3. Third attempt: same nudge, then raise if still broken
- Removed `response_format={"type":"json_object"}` — Ollama interprets it as "any valid JSON" and returns `{}`
- Added `log.debug` of raw model output for easier debugging (`-v` flag)

---

## File Map

```
src/reddit_avatar/
├── cli.py          — Typer CLI: discover, run, harvest, extract, cost, lint
├── config.py       — TopicConfig Pydantic model + YAML loader
├── harvest.py      — Selenium scraper: /top.json + comments
├── extract.py      — Per-post signal extraction (LLM)
├── cluster.py      — Avatar clustering (LLM)
├── synthesize.py   — Full avatar synthesis with citations (LLM)
├── suggest.py      — Subreddit discovery from free-text demand (LLM)  ← new
├── llm.py          — Ollama/OpenAI-compatible wrapper with retry logic
├── schemas.py      — Pydantic models with string→list coercion
├── store.py        — SQLite: posts, signals, cluster, avatars, runs
├── render.py       — Jinja2 → markdown
└── lint.py         — Citation coverage checker

prompts/
├── suggest_subreddits.md   ← new
├── extract_signals.md
├── cluster_avatars.md
└── synthesize_avatar.md
```

---

## Known Limitations

- **Search queries are generated but unused** — the LLM suggests search queries but `/search.json` requires Reddit OAuth. They're stored in the config for future use if OAuth is ever added.
- **Local model quality** — Gemma3 is good enough for extraction and clustering but may produce generic avatars on sparse data. Larger models (via `OLLAMA_MODEL`) produce better results.
- **Selenium is slow** — ~3s per URL. A run with 5 subreddits × 50 posts takes 10–15 minutes to harvest. The disk cache makes subsequent runs instant.
- **No pagination** — Reddit's API caps at 100 posts per request. The pipeline fetches one page per subreddit.
