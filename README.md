# reddit-avatar

Config-driven pipeline: Reddit subject → PhD-depth avatar markdown report.

## Install

```sh
uv sync
cp .env.example .env  # add ANTHROPIC_API_KEY
```

## Usage

```sh
uv run reddit-avatar run configs/example_homelab.yaml
uv run reddit-avatar harvest configs/example_homelab.yaml
uv run reddit-avatar cost --run <run_id>
uv run reddit-avatar lint output/avatars/<file>.md
```

Reports land in `./output/avatars/`.

## Pipeline

1. **harvest** — scrape `reddit.com/r/<sub>/search.json` + top-level comments; cache raw JSON; upsert to SQLite.
2. **extract** — Haiku turns each post into structured signals (pains, desires, JTBD, vocab, demographic tells, verbatim quotes).
3. **cluster** — Opus groups signals into 1–4 avatars, justifying N from signal variance.
4. **synthesize** — Opus writes each avatar; every claim cites a `post_id`.
5. **lint** — rejects runs under 80% citation coverage.
6. **render** — Jinja → markdown with Obsidian frontmatter.

## Config

See `configs/example_homelab.yaml`.


## Overall 

  ---
  1. reddit-avatar discover "<your demand>"

  You type a free-text research intent, e.g.:

  ▎ "I want to understand people building their first homelab"

  ---
  2. LLM suggests subreddits (suggest.py)

  Gemma3 (via Ollama) reads your demand and returns:
  - A short topic label (e.g. "homelab beginners")
  - 4–8 relevant subreddits (e.g. homelab, selfhosted, DataHoarder)
  - 3–6 search queries (currently unused since we skip search)

  ---
  3. Harvest (harvest.py)

  A headless Chrome browser visits each subreddit's /top.json, collects the top posts, then fetches comments for
   each post. Everything is cached on disk so re-runs are instant.

  ---
  4. Extract signals (extract.py)

  For each post, Gemma3 reads the title + body + comments and extracts:
  - Pains, desires, vocabulary, demographics, jobs-to-be-done, verbatim quotes

  ---
  5. Cluster (cluster.py)

  Gemma3 groups all signals into 1–4 distinct user archetypes and justifies the number.

  ---
  6. Synthesize (synthesize.py)

  Gemma3 writes a PhD-depth profile for each archetype — demographics, motivations, fears, language patterns —
  with every claim citing the post it came from.

  ---
  7. Render + Lint (render.py, lint.py)

  The profiles are written to a Markdown file in output/avatars/. A linter then checks that ≥80% of bullet
  points have citations.

  ---
  Output: a single Markdown report with richly detailed user avatars grounded in real Reddit discussions.
