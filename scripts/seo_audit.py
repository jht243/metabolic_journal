#!/usr/bin/env python3
"""CLI entry point for the SEO audit engine."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

console = Console()


@click.command()
@click.option("--json", "json_output", is_flag=True, help="Machine-readable JSON output")
@click.option("--verbose", is_flag=True, help="Show info-level findings")
@click.option("--fail-on-error", is_flag=True, help="Exit 1 if any errors are found")
@click.option("--max-pages", default=200, type=int, help="Maximum pages to crawl")
@click.option("--no-follow", is_flag=True, help="Only crawl seed pages")
def main(json_output: bool, verbose: bool, fail_on_error: bool, max_pages: int, no_follow: bool) -> None:
    """Run The Metabolic Journal SEO audit."""
    from src.config import settings
    from src.seo.audit import run_audit

    if not json_output:
        console.print(Panel(f"[bold]{settings.site_name} - SEO Audit[/bold]", style="blue"))
        console.print(f"Max pages: {max_pages}; follow links: {not no_follow}\n")

    started = time.time()
    report = run_audit(max_pages=max_pages, follow_links=not no_follow)
    elapsed = round(time.time() - started, 1)

    if json_output:
        payload = report.to_dict()
        payload["elapsed_seconds"] = elapsed
        click.echo(json.dumps(payload, indent=2))
    else:
        _print_report(report, verbose=verbose, elapsed=elapsed)

    if fail_on_error and report.errors:
        sys.exit(1)


def _print_report(report, *, verbose: bool, elapsed: float) -> None:
    summary = Table(title="Audit Summary", show_header=False)
    summary.add_column("Metric", style="bold")
    summary.add_column("Value")
    summary.add_row("Pages crawled", str(report.pages_crawled))
    summary.add_row("Pages clean", str(report.pages_ok))
    summary.add_row("Errors", f"[red]{len(report.errors)}[/red]" if report.errors else "[green]0[/green]")
    summary.add_row("Warnings", f"[yellow]{len(report.warnings)}[/yellow]" if report.warnings else "[green]0[/green]")
    summary.add_row("Info", str(len(report.info)))
    summary.add_row("Duration", f"{elapsed:.1f}s")
    console.print(summary)

    if report.errors:
        console.print(f"\n[bold red]Errors ({len(report.errors)}):[/bold red]")
        _print_findings(report.errors)

    if report.warnings:
        console.print(f"\n[bold yellow]Warnings ({len(report.warnings)}):[/bold yellow]")
        _print_findings(report.warnings)

    if verbose and report.info:
        console.print(f"\n[bold]Info ({len(report.info)}):[/bold]")
        _print_findings(report.info)


def _print_findings(findings) -> None:
    table = Table(show_header=True)
    table.add_column("Path", style="cyan", max_width=48)
    table.add_column("Category", style="bold", max_width=18)
    table.add_column("Message")
    for finding in findings:
        table.add_row(finding.path, finding.category, finding.message)
    console.print(table)


if __name__ == "__main__":
    main()
