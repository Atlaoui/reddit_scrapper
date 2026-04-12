"""Render a Report to markdown via Jinja2."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from slugify import slugify

from .schemas import Report

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


def render_report(report: Report, output_dir: str | Path) -> Path:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(default=False),
        trim_blocks=False,
        lstrip_blocks=False,
    )
    tpl = env.get_template("avatar_report.md.j2")
    md = tpl.render(report=report)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"{slugify(report.topic)}-{date}.md"
    path = out / filename
    path.write_text(md, encoding="utf-8")
    return path
