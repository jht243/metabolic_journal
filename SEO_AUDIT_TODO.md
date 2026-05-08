# SEO Audit + Auto-Fix Engine

## Done

- Added `src/seo/audit.py`, a zero-network Flask test-client crawler that extracts SEO signals, follows internal links, checks cluster and sitemap reachability, and returns an `AuditReport`.
- Added `scripts/seo_audit.py` for manual and CI usage with `--json`, `--verbose`, `--fail-on-error`, `--max-pages`, and `--no-follow`.
- Added `src/seo/content_fixer.py`, a budget-capped LandingPage auto-fixer for missing H1 and thin content findings.
- Added render-time Jinja filters in `server.py`:
  - `seo_title`: trims long titles at a word boundary.
  - `seo_desc`: trims descriptions at sentence/phrase/word boundaries and appends `...`.
- Updated `templates/_base.html.j2` so SEO-critical title, description, Open Graph, and Twitter tags use those filters.
- Added canonical fallback to `request.url` in the base template.
- Added `run_daily.py` with distribution first, then SEO audit and auto-fix.
- Added a Render cron service in `render.yaml` that runs `python run_daily.py` daily at 14:00 UTC.

## Left To Build

- Add a richer distribution phase if the site later has a full scrape/generate/report pipeline like the reference repos.
- Decide whether strict JSON-LD requirements should apply to every static marketing page or only to SEO/content pages.
- Add automated tests around the parser and CLI once the site has a stable test harness.

## Key Files

- `src/seo/audit.py`: crawls the local Flask app, parses SEO tags/headings/links/JSON-LD, and produces structured findings.
- `src/seo/content_fixer.py`: applies LLM-powered fixes only to `LandingPage` rows.
- `scripts/seo_audit.py`: on-demand audit CLI for local checks and CI gates.
- `run_daily.py`: daily maintenance runner; runs distribution first, then SEO audit and optional auto-fix.
- `render.yaml`: defines the web service and the daily Render cron service.
- `server.py`: registers the `seo_title` and `seo_desc` Jinja filters.
- `templates/_base.html.j2`: applies the filters to title, meta description, OG, Twitter, and canonical tags.

## How To Test

Quick smoke test:

```bash
python scripts/seo_audit.py --max-pages 10 --no-follow
```

Full audit:

```bash
python scripts/seo_audit.py
```

JSON output:

```bash
python scripts/seo_audit.py --json --max-pages 50
```

CI gate:

```bash
python scripts/seo_audit.py --fail-on-error
```

Verbose mode, including info-level thin-content findings:

```bash
python scripts/seo_audit.py --verbose
```

Daily pipeline dry run:

```bash
python run_daily.py --dry-run --max-pages 50
```
