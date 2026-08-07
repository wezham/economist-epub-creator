#!/usr/bin/env python3
"""Run the Economist EPUB generator with a temporary Playwright login session."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATOR = REPO_ROOT / "economist.py"
VALIDATOR = Path(__file__).with_name("validate_epub.py")
EPUB_DIR = REPO_ROOT / "editions" / "epubs"


def cookie_header(cookies: list[dict]) -> str:
    economist_cookies = [
        cookie
        for cookie in cookies
        if cookie.get("name")
        and cookie.get("value")
        and (
            cookie.get("domain") == ".economist.com"
            or cookie.get("domain", "").endswith(".economist.com")
            or cookie.get("domain") == "www.economist.com"
        )
    ]
    if not economist_cookies:
        raise RuntimeError("No Economist cookies were found in the test session")
    return "; ".join(
        f"{cookie['name']}={cookie['value']}" for cookie in economist_cookies
    )


def newest_epub(previous: dict[Path, int]) -> Path:
    generated = [
        path
        for path in EPUB_DIR.glob("*.epub")
        if path not in previous or path.stat().st_mtime_ns > previous[path]
    ]
    if not generated:
        raise RuntimeError("The generator did not produce a new EPUB")
    return max(generated, key=lambda path: path.stat().st_mtime)


def main() -> int:
    if not GENERATOR.is_file():
        raise RuntimeError(f"Generator not found: {GENERATOR}")

    previous_epubs = {
        path: path.stat().st_mtime_ns for path in EPUB_DIR.glob("*.epub")
    }
    with tempfile.TemporaryDirectory(prefix="economist-playwright-") as profile:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                profile,
                channel="chrome" if shutil.which("google-chrome") else None,
                headless=False,
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(
                "https://www.economist.com/weeklyedition",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            print(
                "Chrome is open. Sign in to Economist in that window, return "
                "to this terminal, and press Enter.",
                flush=True,
            )
            input()
            page.goto(
                "https://www.economist.com/weeklyedition",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            cookies = context.cookies(["https://www.economist.com"])
            header = cookie_header(cookies)
            user_agent = page.evaluate("navigator.userAgent")
            context.close()

        environment = os.environ.copy()
        environment["ECONOMIST_COOKIE"] = header
        environment["ECONOMIST_USER_AGENT"] = user_agent
        try:
            subprocess.run(
                [sys.executable, str(GENERATOR)],
                cwd=REPO_ROOT,
                env=environment,
                check=True,
            )
        finally:
            environment.pop("ECONOMIST_COOKIE", None)
            environment.pop("ECONOMIST_USER_AGENT", None)
            header = ""

    epub = newest_epub(previous_epubs)
    subprocess.run(
        [sys.executable, str(VALIDATOR), str(epub)],
        cwd=REPO_ROOT,
        check=True,
    )
    epubcheck = shutil.which("epubcheck")
    if epubcheck:
        subprocess.run([epubcheck, str(epub)], cwd=REPO_ROOT, check=True)
    print(f"Authenticated end-to-end test passed: {epub.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
