"""Typer CLI wiring all pipeline stages."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console

from .cluster import cluster as cluster_stage
from .config import Limits, TopicConfig
from .extract import extract_all
from .harvest import harvest as harvest_stage
from .lint import lint_file
from .llm import LLM
from .render import render_report
from .schemas import AvatarProfile, ClusterResult, Report
from .store import Store
from .suggest import suggest_subreddits
from .synthesize import synthesize

app = typer.Typer(add_completion=False, help="Reddit → avatar markdown report pipeline.")
console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _run_pipeline(cfg: TopicConfig, verbose: bool) -> None:
    """Shared pipeline: harvest → extract → cluster → synthesize → render → lint.

    Resumes an existing run if the same config was seen before, skipping stages
    that already completed successfully.
    """
    _setup_logging(verbose)
    store = Store()
    llm = LLM()

    config_hash = cfg.fingerprint()
    existing_run = store.find_run(config_hash)
    if existing_run:
        run_id = existing_run
        console.print(f"[bold cyan]Resuming run {run_id}[/] — {cfg.topic}")
    else:
        run_id = store.start_run(cfg.topic, config_hash)
        console.print(f"[bold cyan]Run {run_id}[/] — {cfg.topic}")

    try:
        # Stage 1: Harvest (HTTP responses are disk-cached; posts are upserted)
        console.print("[yellow]Harvesting…[/]")
        n_posts = harvest_stage(cfg, store)
        console.print(f"  fetched {n_posts} posts")

        # Stage 2: Extract (skips posts already processed for this prompt version)
        console.print("[yellow]Extracting signals…[/]")
        n_sig = extract_all(run_id, store, llm)
        if n_sig:
            console.print(f"  extracted {n_sig} new posts · ${llm.total_usd:.4f}")
        else:
            console.print("  [dim]all signals already cached[/]")

        if cfg.limits.max_usd and llm.total_usd > cfg.limits.max_usd:
            raise RuntimeError(f"cost cap hit: ${llm.total_usd:.2f} > ${cfg.limits.max_usd:.2f}")

        # Stage 3: Cluster (cached in runs.cluster_json)
        cached_cluster = store.get_cluster(run_id)
        if cached_cluster:
            console.print("[yellow]Clustering…[/] [dim](cached)[/]")
            clusters = ClusterResult.model_validate_json(cached_cluster)
        else:
            console.print("[yellow]Clustering…[/]")
            clusters = cluster_stage(run_id, store, llm, cfg.avatars.target_count)
            store.save_cluster(run_id, clusters.model_dump_json())
        console.print(f"  N={len(clusters.avatars)} — {clusters.n_justification}")

        # Stage 4: Synthesize (cached in avatars table)
        cached_profiles = store.get_avatars(run_id)
        if cached_profiles:
            console.print("[yellow]Synthesizing avatars…[/] [dim](cached)[/]")
            profiles = [AvatarProfile.model_validate_json(p) for p in cached_profiles]
        else:
            console.print("[yellow]Synthesizing avatars…[/]")
            profiles = synthesize(run_id, store, llm, clusters)

        signal_count = len(store.signals_for_run(run_id))
        report = Report(
            topic=cfg.topic,
            subreddits=cfg.subreddits,
            generated_at=datetime.now(timezone.utc).isoformat(),
            run_id=run_id,
            post_count=len(store.post_ids()),
            signal_count=signal_count,
            cost_usd=store.run_cost(run_id),
            avatars=profiles,
            cluster_justification=clusters.n_justification,
        )
        path = render_report(report, cfg.output.path)
        console.print(f"[green]✓[/] wrote {path}")

        lint_res = lint_file(path, store)
        console.print(
            f"  lint: {lint_res['cited']}/{lint_res['bullets']} bullets cited "
            f"({lint_res['rate']:.0%}) · "
            f"{'[green]PASS[/]' if lint_res['ok'] else '[red]FAIL[/]'}"
        )
        store.finish_run(run_id, "ok" if lint_res["ok"] else "lint_failed")
        console.print(f"[bold]Total cost:[/] ${store.run_cost(run_id):.4f}")
    except Exception:
        store.finish_run(run_id, "error")
        raise
    finally:
        store.close()


@app.command()
def run(
    config: Path = typer.Argument(..., exists=True, readable=True),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
):
    """End-to-end: harvest → extract → cluster → synthesize → render."""
    cfg = TopicConfig.load(config)
    _run_pipeline(cfg, verbose)


@app.command()
def discover(
    demand: str = typer.Argument(..., help="Natural language research intent"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
    max_usd: float = typer.Option(5.0, "--max-usd", help="Cost cap in USD"),
    posts_per_sub: int = typer.Option(50, "--posts", help="Posts to fetch per subreddit"),
):
    """Ask LLM to suggest subreddits from a demand, then run the full pipeline."""
    _setup_logging(verbose)
    llm = LLM()
    console.print("[yellow]Asking LLM to suggest subreddits…[/]")
    suggestion = suggest_subreddits(demand, llm)
    console.print(f"  topic      : [bold]{suggestion.topic}[/]")
    console.print(f"  subreddits : {suggestion.subreddits}")
    console.print(f"  queries    : {suggestion.search_queries}")

    cfg = TopicConfig(
        topic=suggestion.topic,
        subreddits=suggestion.subreddits,
        search_queries=suggestion.search_queries,
        limits=Limits(posts_per_sub=posts_per_sub, max_usd=max_usd),
    )
    _run_pipeline(cfg, verbose)


@app.command("harvest")
def harvest_cmd(
    config: Path = typer.Argument(..., exists=True, readable=True),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
):
    """Stage 1 only: scrape and cache posts."""
    _setup_logging(verbose)
    cfg = TopicConfig.load(config)
    store = Store()
    n = harvest_stage(cfg, store)
    console.print(f"[green]✓[/] harvested {n} posts")
    store.close()


@app.command("extract")
def extract_cmd(
    run_id: int = typer.Option(..., "--run"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
):
    """Stage 2 only: extract signals for an existing run."""
    _setup_logging(verbose)
    store = Store()
    llm = LLM()
    n = extract_all(run_id, store, llm)
    console.print(f"[green]✓[/] extracted {n} posts · ${llm.total_usd:.4f}")
    store.close()


@app.command()
def cost(run_id: int = typer.Option(..., "--run")):
    """Show USD spent on a run."""
    store = Store()
    console.print(f"Run {run_id}: ${store.run_cost(run_id):.4f}")
    store.close()


@app.command("lint")
def lint_cmd(path: Path = typer.Argument(..., exists=True, readable=True)):
    """Verify citation coverage of a rendered report."""
    store = Store()
    res = lint_file(path, store)
    console.print(res)
    store.close()
    if not res["ok"]:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
