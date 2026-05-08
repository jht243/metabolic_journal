#!/usr/bin/env python3
"""Daily maintenance pipeline for The Metabolic Journal.

This repository does not currently have a broader scrape/analyze/report
orchestrator, so this runner captures the existing publish-maintenance work:
IndexNow distribution first, then SEO audit and auto-fix. All SEO phases are
non-fatal by design.
"""
from __future__ import annotations

import logging
import sys
import time

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config import settings

console = Console()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_daily")


@click.command()
@click.option("--dry-run", is_flag=True, help="Run checks without submitting URLs or applying LLM fixes")
@click.option("--skip-indexnow", is_flag=True, help="Skip IndexNow distribution")
@click.option("--skip-autofix", is_flag=True, help="Run the SEO audit but skip LLM-powered fixes")
@click.option("--max-pages", default=200, type=int, help="Maximum pages for SEO audit crawl")
def main(dry_run: bool, skip_indexnow: bool, skip_autofix: bool, max_pages: int) -> None:
    """Run daily distribution and SEO maintenance."""
    console.print(Panel(f"[bold]{settings.site_name} - Daily Pipeline[/bold]", style="blue"))
    started = time.time()
    results: dict[str, dict] = {}

    console.print("\n[bold cyan]Phase 1:[/bold cyan] Distribution / IndexNow...")
    if skip_indexnow:
        results["distribution"] = {"status": "skipped", "reason": "--skip-indexnow"}
        console.print("  [dim]Skipped[/dim]")
    else:
        try:
            if dry_run:
                from src.seo.cluster_topology import all_seo_paths

                static_paths = {"/", "/guides", "/tools", "/about", "/assessment", "/briefing"}
                urls = [f"{settings.canonical_site_url}{path}" for path in sorted(static_paths | set(all_seo_paths()))]
                results["distribution"] = {"status": "dry_run", "urls": len(urls)}
                console.print(f"  [dim]Dry run: would submit {len(urls)} URL(s)[/dim]")
            else:
                from scripts.indexnow_submit import collect_urls
                from src.distribution import indexnow

                urls = [url for url, _kind, _entity_id in collect_urls()]
                outcome = indexnow.submit_urls(urls)
                results["distribution"] = {
                    "status": "ok" if outcome.success else "error",
                    "submitted": outcome.submitted,
                    "status_code": outcome.status_code,
                    "response": outcome.response_snippet,
                }
                style = "green" if outcome.success else "yellow"
                console.print(f"  [{style}]IndexNow: {outcome.status_code}, submitted={outcome.submitted}[/{style}]")
        except Exception as exc:
            logger.warning("Distribution failed: %s", exc, exc_info=True)
            results["distribution"] = {"status": "error", "error": str(exc)}
            console.print(f"  [yellow]![/yellow] Distribution failed (non-fatal): {exc}")

    console.print("\n[bold cyan]Phase 2:[/bold cyan] SEO audit...")
    try:
        from src.seo.audit import run_audit

        seo_report = run_audit(max_pages=max_pages)
        results["seo_audit"] = {
            "pages_crawled": seo_report.pages_crawled,
            "errors": len(seo_report.errors),
            "warnings": len(seo_report.warnings),
        }
        if seo_report.errors:
            console.print(
                f"  [yellow]![/yellow] SEO audit: {seo_report.pages_crawled} pages, "
                f"{len(seo_report.errors)} errors, {len(seo_report.warnings)} warnings"
            )
            for finding in seo_report.errors:
                console.print(f"        [red]error:[/red] {finding}")
        else:
            console.print(
                f"  [green]OK[/green] SEO audit: {seo_report.pages_crawled} pages, "
                f"0 errors, {len(seo_report.warnings)} warnings"
            )

        console.print("\n[bold cyan]Phase 2b:[/bold cyan] SEO auto-fix...")
        if skip_autofix or dry_run:
            reason = "--skip-autofix" if skip_autofix else "--dry-run"
            results["seo_autofix"] = {"status": "skipped", "reason": reason, "fixed": 0}
            console.print(f"  [dim]Skipped ({reason})[/dim]")
        else:
            try:
                from src.seo.content_fixer import fix_content_issues

                fix_result = fix_content_issues(seo_report)
                results["seo_autofix"] = fix_result
                if fix_result.get("fixed", 0) > 0:
                    console.print(
                        f"  [green]OK[/green] Fixed {fix_result['fixed']} page(s), "
                        f"${fix_result.get('total_cost_usd', 0):.4f}"
                    )
                else:
                    console.print(f"  [dim]Nothing fixed: {fix_result.get('reason', fix_result.get('status'))}[/dim]")
            except Exception as exc:
                logger.warning("SEO auto-fix failed: %s", exc, exc_info=True)
                results["seo_autofix"] = {"status": "error", "error": str(exc)}
                console.print(f"  [yellow]![/yellow] SEO auto-fix failed (non-fatal): {exc}")
    except Exception as exc:
        logger.warning("SEO audit failed: %s", exc, exc_info=True)
        results["seo_audit"] = {"status": "error", "error": str(exc)}
        console.print(f"  [yellow]![/yellow] SEO audit failed (non-fatal): {exc}")

    _print_summary(results, time.time() - started)


def _print_summary(results: dict[str, dict], elapsed: float) -> None:
    table = Table(title="Pipeline Summary")
    table.add_column("Phase", style="bold")
    table.add_column("Result")
    for phase, result in results.items():
        table.add_row(phase, str(result))
    table.add_row("duration_seconds", f"{elapsed:.1f}")
    console.print("\n")
    console.print(table)


if __name__ == "__main__":
    sys.exit(main())
