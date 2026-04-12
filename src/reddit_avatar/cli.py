"""Typer CLI wiring all pipeline stages."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console

from .cluster import cluster as cluster_stage
from .config import TopicConfig
from .extract import extract_all
from .harvest import harvest as harvest_stage
from .lint import lint_file
from .llm import LLM
from .render import render_report
from .schemas import Report
from .store import Store
from .synthesize import synthesize

app = typer.Typer(add_completion=False, help="Reddit → avatar markdown report pipeline.")
console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
def run(
    config: Path = typer.Argument(..., exists=True, readable=True),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
):
    """End-to-end: harvest → extract → cluster → synthesize → render."""
    _setup_logging(verbose)
    cfg = TopicConfig.load(config)
    store = Store()
    llm = LLM()
    run_id = store.start_run(cfg.topic, cfg.fingerprint())
    console.print(f"[bold cyan]Run {run_id}[/] — {cfg.topic}")

    try:
        console.print("[yellow]Harvesting…[/]")
        n_posts = harvest_stage(cfg, store)
        console.print(f"  fetched {n_posts} posts")

        console.print("[yellow]Extracting signals…[/]")
        n_sig = extract_all(run_id, store, llm)
        console.print(f"  extracted {n_sig} new posts · ${llm.total_usd:.4f}")

        if cfg.limits.max_usd and llm.total_usd > cfg.limits.max_usd:
            raise RuntimeError(f"cost cap hit: ${llm.total_usd:.2f} > ${cfg.limits.max_usd:.2f}")

        console.print("[yellow]Clustering…[/]")
        clusters = cluster_stage(run_id, store, llm, cfg.avatars.target_count)
        console.print(f"  N={len(clusters.avatars)} — {clusters.n_justification}")

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
