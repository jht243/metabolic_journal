"""Auto-inject contextual internal links into page HTML.

Scans HTML content for mentions of keywords associated with other pages
in the cluster topology and wraps the first occurrence of each keyword
in an <a> tag pointing to the relevant page.
"""
from __future__ import annotations

import re
from html import escape

from src.seo.cluster_topology import _ANCHOR

# Keywords to match → (path, display_text).  Built once at import time.
# We extract short trigger phrases from the page slug and title.
_LINK_TARGETS: list[tuple[re.Pattern, str, str]] = []

def _build_link_targets():
    """Build keyword→path mapping from the cluster topology anchors."""
    if _LINK_TARGETS:
        return

    # Map of keywords → path, sorted longest-first to prefer specific matches
    entries: list[tuple[str, str]] = []

    for path, anchor in _ANCHOR.items():
        if path.startswith("/tools/") or path.startswith("/programs/"):
            continue

        slug = path.rstrip("/").split("/")[-1]
        keywords_for_path: list[str] = []

        slug_phrases = {
            # Peptide names
            "bpc-157": ["BPC-157"],
            "ipamorelin": ["ipamorelin"],
            "sermorelin": ["sermorelin"],
            "cjc-1295": ["CJC-1295"],
            "tb-500": ["TB-500"],
            "epithalon": ["epithalon"],
            "semax": ["semax"],
            "selank": ["selank"],
            "aod-9604": ["AOD-9604"],
            "igf-1-lr3": ["IGF-1 LR3"],
            "glp-1": ["GLP-1 peptides", "semaglutide", "tirzepatide"],
            "hgh": ["HGH peptides"],
            "nad": ["NAD+"],
            "collagen": ["collagen peptides"],
            "wolverine-stack": ["wolverine stack"],
            "ghrp": ["GHRP", "growth hormone releasing peptide"],
            "hgh-vs-peptides": ["HGH vs peptides"],
            "ipamorelin-hgh-frag-stack": ["HGH fragment 176-191"],
            "nad-longevity": ["NAD+ longevity"],
            # Conditions
            "insulin-resistance": ["insulin resistance"],
            "metabolic-syndrome": ["metabolic syndrome"],
            "hypothyroidism": ["hypothyroidism"],
            "osteopenia": ["osteopenia"],
            "osteoporosis": ["osteoporosis"],
            "pcos": ["PCOS"],
            "sleep-apnea": ["sleep apnea"],
            "chronic-fatigue-syndrome": ["chronic fatigue syndrome"],
            "upper-airway-resistance": ["upper airway resistance"],
            # Biomarkers
            "fasting-insulin": ["fasting insulin"],
            "free-testosterone": ["free testosterone"],
            "cortisol-levels": ["cortisol levels"],
            "shbg": ["SHBG"],
            "bone-density-t-score": ["T-score"],
            "heart-rate-variability": ["heart rate variability", "HRV"],
            "vitamin-d-levels": ["vitamin D"],
            # Symptoms
            "sleep-inertia": ["sleep inertia"],
            "brain-fog": ["brain fog"],
            "perimenopause": ["perimenopause"],
        }

        if slug in slug_phrases:
            keywords_for_path.extend(slug_phrases[slug])

        for kw in keywords_for_path:
            entries.append((kw, path))

    # Sort longest keywords first so "GLP-1 peptides" matches before "GLP-1"
    entries.sort(key=lambda e: -len(e[0]))

    for kw, path in entries:
        pattern = re.compile(
            r"(?<![<\w/\"-])(" + re.escape(kw) + r")(?![^<]*>)(?![^<]*</a>)",
            re.IGNORECASE,
        )
        _LINK_TARGETS.append((pattern, path, kw))


def inject_internal_links(html: str, current_path: str) -> str:
    """Replace first occurrence of each keyword with an internal link.

    Skips the current page's own keywords to avoid self-links.
    Only links each keyword once to avoid over-optimization.
    """
    _build_link_targets()
    if not html:
        return html

    norm_current = "/" + current_path.lstrip("/").rstrip("/")
    linked_paths: set[str] = set()
    max_links = 5

    for pattern, path, display in _LINK_TARGETS:
        if len(linked_paths) >= max_links:
            break
        if path == norm_current:
            continue
        if path in linked_paths:
            continue

        def _make_link(match: re.Match) -> str:
            return f'<a href="{path}">{match.group(1)}</a>'

        new_html, count = pattern.subn(_make_link, html, count=1)
        if count > 0:
            html = new_html
            linked_paths.add(path)

    return html
