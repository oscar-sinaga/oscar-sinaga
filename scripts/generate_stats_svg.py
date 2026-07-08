#!/usr/bin/env python3
"""Generate a self-hosted GitHub stats card as a static SVG.

Why: the public github-readme-stats instance is frequently rate-limited and
fails to render. This script computes the stats itself and writes a static SVG
that is committed to the repo, so it always loads (no third-party runtime at
view time). It is refreshed on a schedule by a GitHub Action using GITHUB_TOKEN.

Usage:
    GITHUB_TOKEN=... python scripts/generate_stats_svg.py [username] [out.svg]
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

USER = sys.argv[1] if len(sys.argv) > 1 else "oscar-sinaga"
OUT = sys.argv[2] if len(sys.argv) > 2 else "assets/github-stats.svg"
API = "https://api.github.com"

# Languages we don't want to count as "code" in the breakdown.
LANG_EXCLUDE = {"Roff", "TeX"}

# Notebooks are Python; GitHub counts their (output-inflated) bytes as a
# separate "Jupyter Notebook" language, which otherwise dwarfs everything.
# Fold them into Python so the breakdown reflects the actual language used.
LANG_RENAME = {"Jupyter Notebook": "Python"}

DISPLAY_NAME = "Oscar Sinaga"

# tokyonight-ish palette
BG = "#1a1b27"
BORDER = "#2a2e42"
TITLE = "#70a5fd"
TEXT = "#c0caf5"
MUTED = "#a9b1d6"
ACCENT = "#bf91f3"

LANG_COLORS = {
    "Python": "#3572A5",
    "Jupyter Notebook": "#DA5B0B",
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "Vue": "#41b883",
    "Svelte": "#ff3e00",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "Shell": "#89e051",
    "Dockerfile": "#384d54",
    "Makefile": "#427819",
}


def api(path: str) -> object:
    req = urllib.request.Request(API + path)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "stats-card-generator")
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


# Used only when the API is unreachable (e.g. generating locally behind a
# proxy). In CI with GITHUB_TOKEN the real values below are computed live.
FALLBACK = {
    "name": "Oscar Sinaga",
    "public_repos": 28,
    "followers": 3,
    "following": 6,
    "since": "2021",
    "stars": 3,
    "langs": {
        "Python": 88,
        "Dockerfile": 4,
        "HTML": 3,
        "Shell": 3,
        "PLpgSQL": 2,
    },
}


def collect() -> dict:
    try:
        user = api(f"/users/{USER}")
    except Exception as exc:  # noqa: BLE001 - fall back to known values
        print(f"API unavailable ({exc}); using fallback data", file=sys.stderr)
        return dict(FALLBACK)

    repos: list[dict] = []
    page = 1
    while True:
        batch = api(f"/users/{USER}/repos?per_page=100&page={page}&type=owner")
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    owned = [r for r in repos if not r.get("fork")]
    total_stars = sum(r.get("stargazers_count", 0) for r in owned)

    # Per-repo normalization: each repo contributes its own language mix,
    # normalized to 1, so a single huge (output-inflated notebook) repo can't
    # dominate the whole breakdown by raw bytes. This surfaces the languages
    # actually used across projects, not just whichever repo has the most bytes.
    shares: dict[str, float] = {}
    for r in owned:
        try:
            data = api(f"/repos/{USER}/{r['name']}/languages")
        except urllib.error.HTTPError:
            continue
        repo: dict[str, int] = {}
        for name, size in data.items():
            if name in LANG_EXCLUDE:
                continue
            name = LANG_RENAME.get(name, name)
            repo[name] = repo.get(name, 0) + size
        repo_total = sum(repo.values())
        if repo_total <= 0:
            continue
        for name, size in repo.items():
            shares[name] = shares.get(name, 0.0) + size / repo_total

    langs = {name: round(share * 1000) for name, share in shares.items()}

    api_name = user.get("name")
    return {
        "name": api_name if api_name and api_name != USER else DISPLAY_NAME,
        "public_repos": user.get("public_repos", len(owned)),
        "followers": user.get("followers", 0),
        "following": user.get("following", 0),
        "since": (user.get("created_at") or "2021")[:4],
        "stars": total_stars,
        "langs": langs or dict(FALLBACK["langs"]),
    }


def esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render(d: dict) -> str:
    ranked = sorted(d["langs"].items(), key=lambda kv: kv[1], reverse=True)
    total = sum(size for _, size in ranked) or 1
    # Percentages are relative to the full total; hide anything under ~1%.
    top = [(n, s) for n, s in ranked if s / total >= 0.01][:6] or ranked[:1]

    W, H = 480, 260
    parts: list[str] = []
    parts.append(
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'fill="none" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="{esc(d["name"])} GitHub statistics">'
    )
    parts.append(
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="10" '
        f'fill="{BG}" stroke="{BORDER}"/>'
    )
    parts.append(
        f'<text x="25" y="35" font-family="Segoe UI,Verdana,sans-serif" '
        f'font-size="17" font-weight="700" fill="{TITLE}">'
        f'{esc(d["name"])} — GitHub Stats</text>'
    )

    stats = [
        ("Public repositories", d["public_repos"]),
        ("Stars earned", d["stars"]),
        ("Followers", d["followers"]),
        ("Following", d["following"]),
        ("Member since", d["since"]),
    ]
    y = 68
    for label, value in stats:
        parts.append(
            f'<text x="25" y="{y}" font-family="Segoe UI,Verdana,sans-serif" '
            f'font-size="13" fill="{MUTED}">{esc(label)}</text>'
        )
        parts.append(
            f'<text x="230" y="{y}" font-family="Segoe UI,Verdana,sans-serif" '
            f'font-size="13" font-weight="700" fill="{TEXT}" '
            f'text-anchor="end">{esc(value)}</text>'
        )
        y += 26

    # Top languages
    lx, ly = 260, 62
    parts.append(
        f'<text x="{lx}" y="{ly}" font-family="Segoe UI,Verdana,sans-serif" '
        f'font-size="13" font-weight="700" fill="{ACCENT}">Top Languages</text>'
    )
    row = ly + 22
    for name, size in top:
        pct = size / total * 100
        color = LANG_COLORS.get(name, "#8b8b8b")
        bar_w = max(4, round(pct / 100 * 150))
        parts.append(
            f'<circle cx="{lx + 5}" cy="{row - 4}" r="5" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{lx + 18}" y="{row}" font-family="Segoe UI,Verdana,sans-serif" '
            f'font-size="12" fill="{TEXT}">{esc(name)}</text>'
        )
        parts.append(
            f'<text x="{W - 25}" y="{row}" font-family="Segoe UI,Verdana,sans-serif" '
            f'font-size="11" fill="{MUTED}" text-anchor="end">{pct:.1f}%</text>'
        )
        parts.append(
            f'<rect x="{lx + 18}" y="{row + 4}" width="150" height="4" rx="2" '
            f'fill="{BORDER}"/>'
        )
        parts.append(
            f'<rect x="{lx + 18}" y="{row + 4}" width="{bar_w}" height="4" rx="2" '
            f'fill="{color}"/>'
        )
        row += 28

    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    data = collect()
    svg = render(data)
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {OUT}: repos={data['public_repos']} "
          f"stars={data['stars']} langs={len(data['langs'])}")


if __name__ == "__main__":
    main()
