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
