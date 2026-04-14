# reddit-avatar

Config-driven pipeline: free-text research demand → PhD-depth avatar markdown report, powered by a local LLM and Reddit scraping — no Reddit app required.

## Install

```sh
uv sync
cp .env.example .env   # set OLLAMA_MODEL if needed (default: gemma3)
ollama pull gemma3     # or whichever model you use
```

## Usage

```sh
# Recommended: let the LLM discover subreddits from your demand
uv run reddit-avatar discover "I want to understand people building their first homelab"

# Or run from a hand-crafted YAML config
uv run reddit-avatar run configs/example_homelab.yaml

# Other commands
uv run reddit-avatar harvest configs/example_homelab.yaml
uv run reddit-avatar cost --run <run_id>
uv run reddit-avatar lint output/avatars/<file>.md
```

Reports land in `./output/avatars/`.

## Pipeline

1. **discover** — you provide a free-text demand; the LLM suggests 4–8 relevant subreddits and a topic label.
2. **harvest** — headless Chrome visits each subreddit's `/top.json` and fetches top-level comments. Responses are disk-cached so re-runs are instant.
3. **extract** — the LLM turns each post into structured signals: pains, desires, JTBD, vocabulary, demographic tells, verbatim quotes.
4. **cluster** — the LLM groups signals into 1–4 avatars, justifying N from signal variance.
5. **synthesize** — the LLM writes a PhD-depth profile per avatar; every claim cites a `post_id`.
6. **lint** — rejects runs under 80% citation coverage.
7. **render** — Jinja2 template → markdown with YAML frontmatter.

Each stage is cached in SQLite. Re-running the same demand resumes from where it left off.

## Config

See `configs/example_homelab.yaml`. The `discover` command builds this config automatically.

Environment variables (`.env`):
```
OLLAMA_BASE_URL=http://localhost:11434/v1   # default
OLLAMA_MODEL=gemma3                         # default
```

---

## Scraping Reddit Without a Reddit App — Key Learnings

### What Doesn't Work

| Approach | Why it fails |
|----------|-------------|
| Custom bot User-Agent | Instant 403 |
| `/search.json` (any method) | Requires OAuth regardless of User-Agent |
| `httpx` / `requests` with browser User-Agent | Works for some posts, 403s on search and some individual posts |
| `response_format={"type":"json_object"}` with Ollama | Model returns `{}` — satisfies JSON constraint but ignores schema |

### What Works

**Use Selenium headless Chrome** to fetch JSON endpoints directly. Reddit serves raw JSON to real browsers.

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

opts = Options()
opts.add_argument("--headless=new")
opts.add_argument("--disable-blink-features=AutomationControlled")
opts.add_experimental_option("excludeSwitches", ["enable-automation"])
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

driver.get("https://www.reddit.com/r/homelab/top.json?t=year&limit=100")
body = driver.find_element("tag name", "body").text
data = json.loads(body)
```

**URLs that work without auth:**
```
https://www.reddit.com/r/{subreddit}/top.json?t=year&limit=100
https://www.reddit.com/comments/{post_id}.json?limit=20&depth=1
```

**Rules:**
- Sleep 3s between requests to avoid 429s
- Some posts 403 (NSFW / private) — catch and skip, never retry them
- Cache every response to disk by `SHA256(url)` — re-runs are instant
- `/search.json` always fails without OAuth — pick targeted subreddits instead of relying on search

### Local LLM (Ollama) Quirks

- Models return a string where a list is expected → add a Pydantic `field_validator` that coerces strings to `[string]`
- Models return `{}` when forced with `response_format={"type":"json_object"}` → drop it, rely on prompt instructions
- Models return prose instead of JSON → implement a 3-attempt retry: send the bad response back and ask explicitly for JSON only
- Add `-v` to see what the model actually returned when debugging

### Recommended Stack

| Concern | Solution |
|---------|----------|
| Reddit fetching | Selenium + headless Chrome via `webdriver-manager` |
| Subreddit discovery | LLM given free-text demand → returns subreddit list |
| LLM calls | Ollama (any model) via OpenAI-compatible API at `http://localhost:11434/v1` |
| Caching | Disk cache for HTTP + SQLite for signals/cluster/avatars, keyed by config hash |
| Rate limiting | 3s sleep between requests, skip 403s silently |
