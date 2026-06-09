#!/usr/bin/env python3
"""Scrape the public Harness-Bench website task pages.

The site exposes task descriptions, prompts, hooks, rubrics, graders, and input
file download links. This script records what is public and verifies whether the
linked fixture downloads are actually available.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin


BASE_URL = "https://www.harness-bench.ai/"
DOMAIN_PATHS = [
    "workspace_operations.html",
    "office_business.html",
    "long_running_autonomy.html",
    "software_engineering.html",
    "knowledge_retrieval.html",
    "sre_devops.html",
    "data_analytics.html",
    "vertical_workflows.html",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--download-timeout", type=float, default=5.0)
    parser.add_argument("--download-workers", type=int, default=16)
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    html_dir = output_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    domains = []
    tasks = []
    for domain_path in DOMAIN_PATHS:
        domain_url = urljoin(BASE_URL, domain_path)
        domain_html = fetch_text(domain_url)
        (html_dir / domain_path).write_text(domain_html, encoding="utf-8")
        domain_title = text_between(domain_html, r"<h1[^>]*>", r"</h1>") or domain_path
        domain_slug = domain_path.removesuffix(".html")
        task_links = sorted(
            set(re.findall(r'href="(' + re.escape(domain_slug) + r'/task\d+\.html)"', domain_html)),
            key=task_sort_key,
        )
        domains.append(
            {
                "slug": domain_slug,
                "path": domain_path,
                "url": domain_url,
                "title": strip_tags(domain_title),
                "task_count": len(task_links),
            }
        )
        domain_task_dir = html_dir / domain_slug
        domain_task_dir.mkdir(parents=True, exist_ok=True)
        for task_link in task_links:
            task_url = urljoin(domain_url, task_link)
            task_html = fetch_text(task_url)
            (domain_task_dir / Path(task_link).name).write_text(task_html, encoding="utf-8")
            tasks.append(parse_task_page(domain_slug, task_link, task_url, task_html))
            time.sleep(args.sleep)

    write_json(output_dir / "domains.json", domains)
    write_json(output_dir / "task_manifest.json", tasks)

    download_inputs = [
        {"task_id": task["task_id"], "path": item["path"], "url": item["url"]}
        for task in tasks
        for item in task["input_files"]
    ]
    download_checks = []
    with ThreadPoolExecutor(max_workers=max(1, args.download_workers)) as executor:
        futures = {
            executor.submit(check_url, item["url"], timeout=args.download_timeout): item
            for item in download_inputs
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                check = future.result()
            except Exception as exc:  # pragma: no cover - defensive network guard
                check = {"status_code": 0, "bytes": 0, "error": str(exc)}
            download_checks.append({**check, **item})
    download_checks.sort(key=lambda item: (item["task_id"], item["path"], item["url"]))

    missing = [item for item in download_checks if item["status_code"] != 200]
    write_json(output_dir / "download_url_status.json", download_checks)
    (output_dir / "missing_downloads.txt").write_text(
        "\n".join(f"{item['status_code']} {item['task_id']} {item['path']} {item['url']}" for item in missing)
        + ("\n" if missing else ""),
        encoding="utf-8",
    )
    (output_dir / "site-scrape-summary.json").write_text(
        json.dumps(
            {
                "domain_count": len(domains),
                "task_count": len(tasks),
                "input_file_link_count": len(download_checks),
                "input_file_download_ok": len(download_checks) - len(missing),
                "input_file_download_missing": len(missing),
                "all_downloads_available": not missing,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "pico-benchmark-audit/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def check_url(url: str, *, timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "pico-benchmark-audit/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read()
            return {"status_code": int(response.status), "bytes": len(body), "error": ""}
    except urllib.error.HTTPError as exc:
        return {"status_code": int(exc.code), "bytes": 0, "error": str(exc)}
    except OSError as exc:
        return {"status_code": 0, "bytes": 0, "error": str(exc)}


def parse_task_page(domain_slug: str, task_link: str, url: str, page: str) -> dict[str, Any]:
    task_number = int(re.search(r"task(\d+)\.html", task_link).group(1))  # type: ignore[union-attr]
    h1 = strip_tags(text_between(page, r"<h1[^>]*>", r"</h1>") or "")
    task_id = strip_tags(text_between(page, r"<span class=\"metadata-label\">Task ID</span>\s*<span class=\"metadata-value\">", r"</span>") or "")
    difficulty = strip_tags(text_between(page, r"<span class=\"metadata-label\">Difficulty</span>\s*<span class=\"metadata-value\">", r"</span>") or "")
    tags_block = text_between(page, r"<span class=\"metadata-label\">Tags</span>", r"</div>") or ""
    tags = [strip_tags(item) for item in re.findall(r"<span class=\"tag-pill\">(.*?)</span>", tags_block, flags=re.S)]

    input_files = []
    for row in re.findall(r"<div class=\"file-row\">(.*?)(?=<div class=\"file-row\">|</div>\s*</div>\s*<div id=|</div>\s*</div>\s*<div class=\"card\")", page, flags=re.S):
        name_match = re.search(r"<span class=\"file-name\"[^>]*>(.*?)</span>", row, flags=re.S)
        url_match = re.search(r'data-url="([^"]+)"', row)
        if name_match and url_match:
            input_files.append({"path": strip_tags(name_match.group(1)), "url": html.unescape(url_match.group(1))})

    code_blocks = [html.unescape(strip_tags(block)) for block in re.findall(r"<pre class=\"code-block\"><code>(.*?)</code></pre>", page, flags=re.S)]
    return {
        "domain_slug": domain_slug,
        "task_page": task_link,
        "task_number": task_number,
        "url": url,
        "title": h1,
        "task_id": task_id,
        "difficulty": difficulty,
        "tags": tags,
        "prompt": extract_card_text(page, "task-content"),
        "input_files": input_files,
        "code_blocks": {
            "hooks": code_blocks[0] if len(code_blocks) == 3 else "",
            "llm_rubric": code_blocks[-2] if len(code_blocks) >= 2 else "",
            "completion_grader": code_blocks[-1] if code_blocks else "",
        },
        "code_block_count": len(code_blocks),
    }


def extract_card_text(page: str, card_id: str) -> str:
    match = re.search(rf'<div id="{re.escape(card_id)}" class="card">(.*?)</div>\s*</div>', page, flags=re.S)
    if not match:
        return ""
    return normalize_ws(strip_tags(match.group(1)))


def text_between(text: str, start_pattern: str, end_pattern: str) -> str:
    match = re.search(start_pattern + r"(.*?)" + end_pattern, text, flags=re.S)
    return match.group(1) if match else ""


def strip_tags(value: str) -> str:
    return normalize_ws(re.sub(r"<[^>]+>", "", html.unescape(value)))


def normalize_ws(value: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", value)).strip()


def task_sort_key(path: str) -> int:
    return int(re.search(r"\d+", path).group(0))  # type: ignore[union-attr]


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
