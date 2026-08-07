import requests
from bs4 import BeautifulSoup
import json
import os
from mdutils.mdutils import MdUtils
from markdownify import markdownify as md
import glob
import pathlib
import subprocess
import argparse
import re
import time
import hashlib
from urllib.parse import urljoin, urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _json_scripts(soup: BeautifulSoup, **attributes):
    for script in soup.find_all("script", attributes):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue


def _find_item_list(value):
    if isinstance(value, dict):
        if value.get("@type") == "ItemList" and isinstance(
            value.get("itemListElement"), list
        ):
            return value["itemListElement"]
        for child in value.values():
            result = _find_item_list(child)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _find_item_list(child)
            if result is not None:
                return result
    return None


def extract_article_urls(html: bytes) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for data in _json_scripts(soup, type="application/ld+json"):
        items = _find_item_list(data)
        if items is None:
            continue
        urls = []
        for entry in items:
            item = entry.get("item", {}) if isinstance(entry, dict) else {}
            url = item.get("url") if isinstance(item, dict) else None
            if url:
                urls.append(url)
        if urls:
            return urls
    # Current weekly-edition pages may render article cards as semantic links
    # without an ItemList. Dated Economist paths distinguish articles from
    # navigation and section links.
    urls = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        url = urljoin("https://www.economist.com", anchor["href"])
        parsed = urlparse(url)
        if parsed.netloc not in {"economist.com", "www.economist.com"}:
            continue
        if not re.search(r"/\d{4}/\d{2}/\d{2}/[^/]+/?$", parsed.path):
            continue
        clean_url = f"https://www.economist.com{parsed.path.rstrip('/')}"
        if clean_url not in seen:
            seen.add(clean_url)
            urls.append(clean_url)
    if urls:
        return urls
    raise RuntimeError("Could not find the weekly edition article list")


def _find_cp2_content(value):
    if isinstance(value, dict):
        content = value.get("cp2Content")
        if isinstance(content, dict) and content.get("headline") and content.get("body"):
            return content
        for child in value.values():
            result = _find_cp2_content(child)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _find_cp2_content(child)
            if result is not None:
                return result
    return None


def extract_article_content(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    candidates = list(_json_scripts(soup, id="__NEXT_DATA__"))
    candidates.extend(_json_scripts(soup, type="application/json"))
    for data in candidates:
        content = _find_cp2_content(data)
        if content is not None:
            return content

    article = soup.find("article", {"data-testid": "Article"}) or soup.find("article")
    if article is not None:
        heading = article.find("h1")
        paragraphs = article.find_all(attrs={"data-component": "paragraph"})
        if heading is not None and paragraphs:
            section_meta = soup.find("meta", {"property": "article:section"})
            description_meta = soup.find("meta", {"name": "description"})
            body = []
            seen_images = set()
            for element in article.find_all(
                lambda tag: (
                    tag.name == "p" and tag.get("data-component") == "paragraph"
                )
                or tag.name in {"h2", "h3"}
                or (
                    tag.name == "img"
                    and "/content-assets/images/" in tag.get("src", "")
                    and not re.search(r"\d{8}_DE_[A-Z]{2}\.", tag.get("src", ""))
                    and tag.find_parent("figure") is not None
                )
            ):
                element_text = element.get_text(" ", strip=True)
                if element.name in {"h2", "h3"} and (
                    re.match(r"^From the .+ edition$", element_text)
                    or element_text.startswith("More from ")
                ):
                    break
                if element.name == "p" and element.get_text(" ", strip=True):
                    body.append(
                        {
                            "type": "TEXT",
                            "textHtml": element.decode_contents(),
                        }
                    )
                elif element.name in {"h2", "h3"} and element.get_text(
                    " ", strip=True
                ):
                    body.append(
                        {
                            "type": "CROSSHEAD",
                            "text": element.get_text(" ", strip=True),
                        }
                    )
                elif element.name == "img":
                    image_url = element.get("src")
                    if image_url not in seen_images:
                        seen_images.add(image_url)
                        body.append(
                            {
                                "type": "IMAGE",
                                "url": image_url,
                                "alt": element.get("alt", ""),
                            }
                        )
            return {
                "headline": heading.get_text(" ", strip=True),
                "rubric": (
                    description_meta.get("content", "")
                    if description_meta is not None
                    else ""
                ),
                "section": {
                    "name": (
                        section_meta.get("content", "")
                        if section_meta is not None
                        else ""
                    )
                },
                "printHeadline": "",
                "leadComponent": None,
                "body": body,
            }
    raise RuntimeError(
        "Could not find structured article content; the page may be a login, "
        "paywall, unsupported article, or changed Economist schema."
    )


def _image_extension(content: bytes, content_type: str = "") -> str:
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp"
    if content.lstrip().startswith(b"<svg"):
        return ".svg"
    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
    }.get(content_type)
    if extension:
        return extension
    raise RuntimeError(
        f"Unsupported image content type {content_type or 'unknown'}"
    )


class EconomistEpubCreator:
    EDITIONS_PATH = "./editions"
    PAGE_BREAK = '<div class="pagebreak"></div>'

    def __init__(self, cookie: str):
        self.headers = {
            "User-Agent": os.environ.get(
                "ECONOMIST_USER_AGENT",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36",
            ),
            "Cookie": cookie,
        }
        retry = Retry(
            total=6,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def get_latest_edition(self) -> str:
        """Returns the latest edition of the Economist"""

        response = self.session.get(
            "https://www.economist.com/weeklyedition",
            allow_redirects=False,
            timeout=30,
        )
        if response.status_code in (401, 403):
            raise RuntimeError(
                "Economist rejected the session cookie. "
                "Sign in again and supply the current Cookie header value."
            )
        response.raise_for_status()
        location = response.headers.get("Location")
        if not location:
            raise RuntimeError(
                "The weekly edition response did not redirect. "
                "Check that the supplied Economist session cookie is valid."
            )
        return location.rstrip("/").split("/")[-1]

    def fetch_all_articles_in_edition(self):
        latest_edition = self.get_latest_edition()

        response = self.session.get(
            f"https://www.economist.com/weeklyedition/{latest_edition}",
            allow_redirects=True,
            timeout=30,
        )
        if response.status_code in (401, 403):
            raise RuntimeError(
                "Economist rejected the session cookie while loading the edition. "
                "Sign in again and supply the current Cookie header value."
            )
        response.raise_for_status()

        article_urls = extract_article_urls(response.content)

        edition_path = pathlib.Path(self.EDITIONS_PATH) / latest_edition
        edition_path.mkdir(parents=True, exist_ok=True)

        for article_url in article_urls:
            article_path = edition_path / (
                os.path.basename(article_url.rstrip("/")) + ".html"
            )
            if article_path.is_file() and article_path.stat().st_size > 1_000:
                continue

            time.sleep(1)
            response = self.session.get(
                article_url,
                allow_redirects=True,
                timeout=30,
            )
            response.raise_for_status()

            with open(article_path, "wb") as f:
                f.write(response.content)

    def _write_image_to_file(self, edition: str, url: str) -> str:
        download_url = re.sub(
            r"/width=\d+,quality=80,format=auto/",
            "/width=960,quality=80,format=jpeg/",
            url,
        )
        digest = hashlib.sha256(download_url.encode("utf-8")).hexdigest()[:16]
        edition_path = pathlib.Path(self.EDITIONS_PATH) / edition
        cached = list(edition_path.glob(f"image-{digest}.*"))
        if cached:
            cached_path = cached[0]
            extension = _image_extension(cached_path.read_bytes()[:32])
            if cached_path.suffix.lower() != extension:
                corrected_path = cached_path.with_suffix(extension)
                cached_path.replace(corrected_path)
                cached_path = corrected_path
            return str(cached_path)
        response = self.session.get(
            download_url,
            stream=True,
            timeout=30,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
        content = response.content
        extension = _image_extension(content, content_type)
        image_path = edition_path / f"image-{digest}{extension}"
        image_path.write_bytes(content)
        return str(image_path)

    def write_articles_to_markdown(self, edition: str):
        pathlib.Path(f"{self.EDITIONS_PATH}/markdown_editions").mkdir(
            parents=True, exist_ok=True
        )
        markdown_file = MdUtils(
            file_name=f"{self.EDITIONS_PATH}/markdown_editions/economist_weekly_{edition}.md",
            title="Economist Weekly - " + edition,
        )

        article_count = 0
        for article in glob.glob(f"{self.EDITIONS_PATH}/{edition}/*.html"):
            with open(article) as f:
                article_soup = BeautifulSoup(f.read(), "html.parser")

            try:
                article_content = extract_article_content(str(article_soup))
            except RuntimeError as exc:
                print(f"Unsupported article type: {exc}")
                continue
            article_count += 1

            headline = article_content["headline"]
            sub_header = article_content["rubric"] or ""

            image_file = None
            if article_content.get("leadComponent"):
                image_file = self._write_image_to_file(
                    edition, article_content["leadComponent"]["url"]
                )

            markdown_file.new_header(title=headline, level=1)
            markdown_file.new_line(text=sub_header, bold_italics_code="bi")
            markdown_file.new_line(
                text=article_content["section"].get("name", "")
                or "" + " - " + article_content.get("printHeadline", "")
                or "",
                bold_italics_code="i",
            )
            if image_file:
                markdown_file.new_line(
                    markdown_file.new_inline_image(text="", path=image_file)
                )

            for block in article_content["body"]:

                if block["type"] in ["INFOBOX"]:
                    print("Skipping infobox")
                    continue

                if block["type"] == "CROSSHEAD":
                    markdown_file.new_header(title=block["text"], level=2)
                    continue

                if block["type"] == "IMAGE":
                    image_file = self._write_image_to_file(edition, block["url"])
                    markdown_file.new_line(
                        markdown_file.new_inline_image(
                            text=block.get("alt", ""), path=image_file
                        )
                    )
                    continue

                if block["type"] == "INFOGRAPHIC":
                    image_file = self._write_image_to_file(
                        edition, block["fallback"]["url"]
                    )
                    markdown_file.new_line(
                        markdown_file.new_inline_image(text="", path=image_file)
                    )
                    continue

                if block["type"] == "DIVIDER":
                    markdown_file.new_line(self.PAGE_BREAK)
                    markdown_file.new_line("\n")
                    continue

                if block["type"] == "GENERIC_EMBED":
                    continue

                if "textHtml" not in block:
                    print(block)
                    raise ValueError("Unexpected block type")

                markdown_file.new_line(md(block["textHtml"]) + "\n")

            markdown_file.new_line(self.PAGE_BREAK)
            markdown_file.new_line("\n")

        if article_count == 0:
            raise RuntimeError(
                "No subscriber articles could be parsed; refusing to create an empty EPUB"
            )
        markdown_file.create_md_file()
        return article_count

    def create_epub(self, edition: str):
        pathlib.Path(f"{self.EDITIONS_PATH}/epubs").mkdir(parents=True, exist_ok=True)
        command = [
            "pandoc",
            "-o",
            f"{self.EDITIONS_PATH}/epubs/economist_weekly_{edition}.epub",
            f"{self.EDITIONS_PATH}/markdown_editions/economist_weekly_{edition}.md",
            "--toc=true",
            "--metadata",
            f"title=The Economist Weekly - {edition}",
            "--metadata",
            "lang=en-AU",
            "--css=epub.css",
        ]
        subprocess.run(command, check=True)

    def create_latest_edition_epub(self):
        edition = self.get_latest_edition()
        self.fetch_all_articles_in_edition()
        article_count = self.write_articles_to_markdown(edition)
        self.create_epub(edition)
        print(f"Packaged {article_count} articles from edition {edition}")
        return f"{self.EDITIONS_PATH}/epubs/economist_weekly_{edition}.epub"


def main():
    parser = argparse.ArgumentParser(
        description="Create an EPUB from the latest Economist weekly edition."
    )
    parser.add_argument(
        "--cookie",
        help="Economist Cookie header value. Prefer ECONOMIST_COOKIE to avoid shell history.",
    )
    args = parser.parse_args()
    cookie = args.cookie or os.environ.get("ECONOMIST_COOKIE")
    if not cookie:
        parser.error("set ECONOMIST_COOKIE or pass --cookie")
    output = EconomistEpubCreator(cookie).create_latest_edition_epub()
    print(output)


if __name__ == "__main__":
    main()
