---
name: test-economist-epub
description: Test the Economist EPUB creator end to end with an authenticated browser session, diagnose Economist page-parser changes with Playwright and Beautiful Soup, and validate that the generated EPUB is structurally suitable for Kindle import. Use when Codex needs to test, debug, or repair authenticated Economist weekly-edition EPUB generation.
---

# Test Economist EPUB

Test the generator against a real authenticated Economist session without printing or persisting credentials.

## Workflow

1. Choose the browser surface:
   - In the Codex app with a connected Chrome plugin, use the browser MCP Playwright API.
   - In Codex CLI, run `scripts/run_cli_e2e.py`. It launches a headed, temporary Playwright profile and pauses for the user to sign in.
2. Confirm that `https://www.economist.com/weeklyedition` displays subscriber content.
3. Obtain authentication only from the task-specific Playwright context or an MCP capability explicitly designed to return the Economist session token or cookies. Never scrape password fields, existing browser profiles, cookie databases, or local storage. Never print the token.
4. Pass the value to the process through `ECONOMIST_COOKIE`, not a command-line argument:

   ```bash
   ECONOMIST_COOKIE='<value>' python economist.py
   ```

5. Capture the emitted `.epub` path and validate it:

   ```bash
   python skills/test-economist-epub/scripts/validate_epub.py editions/epubs/<file>.epub
   ```

6. If `epubcheck` is installed, also run `epubcheck <file>.epub`. Treat any error as a failed test.
7. Report the edition, article count, EPUB path, validator results, and any skipped unsupported article types. Redact all authentication values.

For the complete CLI flow, run:

```bash
.venv/bin/python skills/test-economist-epub/scripts/run_cli_e2e.py
```

The runner keeps cookies in memory, passes them to the generator through its subprocess environment, and deletes the temporary browser profile when it exits.

## Diagnose parser failures

Use Playwright to inspect DOM structure and script elements on the failing weekly-edition or article page. Save sanitized HTML only when needed; remove tokens, personal data, and unrelated page content first.

Use Beautiful Soup locally to reproduce selectors against the sanitized HTML:

```python
from bs4 import BeautifulSoup
soup = BeautifulSoup(html, "html.parser")
```

Check these extraction surfaces in order:

1. JSON-LD `ItemList` data on the weekly edition.
2. `__NEXT_DATA__` or other application JSON containing article content.
3. Semantic article markup as a last resort.

Prefer structured page data over visible-text scraping. Patch the narrowest stable extractor, run unit tests against sanitized fixtures, and then repeat the live end-to-end generation and EPUB validation.

## Completion gate

Do not claim success unless:

- the authenticated live run completes;
- at least one subscriber article is included;
- the EPUB validator passes;
- `epubcheck` passes when available; and
- the output opens as an EPUB/Kindle-importable book rather than an HTML login or paywall page.
