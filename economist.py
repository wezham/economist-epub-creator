import requests
from bs4 import BeautifulSoup
import json
import os
import shutil
from mdutils.mdutils import MdUtils
from markdownify import markdownify as md
import glob
import pathlib
import subprocess


class EconomistScraper:
    EDITIONS_PATH = "./editions"

    def __init__(self, cookie: str):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:129.0) Gecko/20100101 Firefox/129.0",
            "Cookie": cookie,
        }

    def get_latest_edition(self) -> str:
        """Returns the latest edition of the Economist"""

        response = requests.get(
            "https://www.economist.com/weeklyedition",
            headers=self.headers,
            allow_redirects=False,
        )
        return response.headers["Location"].split("/")[-1]

    def fetch_all_articles_in_edition(self):
        latest_edition = self.get_latest_edition()

        response = requests.get(
            f"https://www.economist.com/weeklyedition/{latest_edition}",
            headers=self.headers,
            allow_redirects=False,
        )

        response = requests.get(
            f"https://www.economist.com/weeklyedition/{latest_edition}",
            headers=self.headers,
            allow_redirects=False,
        )

        soup = BeautifulSoup(response.content, "html.parser")
        main_content = soup.find("main", {"role": "main", "id": "content"})
        script_tag = main_content.find("script", {"type": "application/ld+json"})
        json_data = script_tag.string
        data = json.loads(json_data)

        for article in data.get("itemListElement"):
            response = requests.get(
                article["item"]["url"], headers=self.headers, allow_redirects=True
            )

            pathlib.Path(f"./{latest_edition}/").mkdir(parents=True, exist_ok=True)

            with open(
                f"{self.EDITIONS_PATH}/{latest_edition}/"
                + os.path.basename(article["item"]["url"])
                + ".html",
                "wb",
            ) as f:
                f.write(response.content)

    def _write_image_to_file(self, edition: str, url: str) -> str:
        response = requests.get(
            url,
            headers=self.headers,
            stream=True,
        )
        file_name = url.split("/")[-1]
        with open(f"{self.EDITIONS_PATH}/{edition}/{file_name}.png", "wb") as f:
            response.raw.decode_content = True
            shutil.copyfileobj(response.raw, f)
        return f"{self.EDITIONS_PATH}/{edition}/{file_name}.png"

    def write_articles_to_markdown(self, edition: str):
        markdown_file = MdUtils(
            file_name=f"{self.EDITIONS_PATH}/markdown_editions/economist_weekly_{edition}.md",
            title="Economist Weekly - " + edition,
        )

        for article in glob.glob(f"{self.EDITIONS_PATH}/{edition}/*.html"):
            with open(article) as f:
                article_soup = BeautifulSoup(f.read(), "html.parser")

            article_body = article_soup.find("script", {"id": "__NEXT_DATA__"})
            if article_body is None:
                print("Unsupported article type")
                continue

            props = json.loads(article_body.string)

            article_content = props["props"]["pageProps"]["cp2Content"]

            headline = article_content["headline"]
            sub_header = article_content["rubric"] or ""

            if article_content["leadComponent"]:
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
                        markdown_file.new_inline_image(text="", path=image_file)
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
                    markdown_file.new_line("{pagebreak}")
                    markdown_file.new_line("\n")
                    continue

                if block["type"] == "GENERIC_EMBED":
                    continue

                if "textHtml" not in block:
                    print(block)
                    raise ValueError("Unexpected block type")

                markdown_file.new_line(md(block["textHtml"]) + "\n")

            markdown_file.new_line("{pagebreak}")
            markdown_file.new_line("\n")

        markdown_file.create_md_file()

    def create_epub(self, edition: str):
        command = [
            "pandoc",
            "-o",
            f"{self.EDITIONS_PATH}/epubs/economist_weekly_{edition}.epub",
            f"{self.EDITIONS_PATH}/markdown_editions/economist_weekly_{edition}.md",
            "--toc=true",
        ]
        subprocess.run(command, check=True)

    def create_latest_edition_epub(self):
        edition = self.get_latest_edition()
        self.fetch_all_articles_in_edition()
        self.write_articles_to_markdown(edition)
        self.create_epub(edition)
