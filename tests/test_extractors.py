import unittest

from economist import _image_extension, extract_article_content, extract_article_urls


class WeeklyEditionExtractorTests(unittest.TestCase):
    def test_extracts_item_list_nested_in_json_ld_graph(self):
        html = b"""
        <html><head>
          <script type="application/ld+json">
            {"@graph":[{"@type":"WebPage"},{"@type":"ItemList",
             "itemListElement":[
               {"item":{"url":"https://www.economist.com/a"}},
               {"item":{"url":"https://www.economist.com/b"}}
             ]}]}
          </script>
        </head></html>
        """
        self.assertEqual(
            extract_article_urls(html),
            [
                "https://www.economist.com/a",
                "https://www.economist.com/b",
            ],
        )

    def test_rejects_page_without_article_list(self):
        with self.assertRaisesRegex(RuntimeError, "article list"):
            extract_article_urls(b"<html><body>Sign in</body></html>")

    def test_extracts_dated_semantic_article_links(self):
        html = b"""
        <main>
          <a href="/finance-and-economics/2026/07/25/a-test-article">Article</a>
          <a href="/finance-and-economics">Section navigation</a>
          <a href="/finance-and-economics/2026/07/25/a-test-article?x=1">Duplicate</a>
        </main>
        """
        self.assertEqual(
            extract_article_urls(html),
            [
                "https://www.economist.com/finance-and-economics/"
                "2026/07/25/a-test-article"
            ],
        )


class ArticleExtractorTests(unittest.TestCase):
    def test_extracts_nested_next_data_content(self):
        html = """
        <script id="__NEXT_DATA__" type="application/json">
          {"props":{"pageProps":{"cp2Content":{
            "headline":"Test headline",
            "body":[{"type":"TEXT","textHtml":"Test body"}]
          }}}}
        </script>
        """
        content = extract_article_content(html)
        self.assertEqual(content["headline"], "Test headline")

    def test_extracts_content_from_generic_application_json(self):
        html = """
        <script type="application/json">
          {"state":{"article":{"cp2Content":{
            "headline":"Moved schema",
            "body":[{"type":"TEXT","textHtml":"Test body"}]
          }}}}
        </script>
        """
        content = extract_article_content(html)
        self.assertEqual(content["headline"], "Moved schema")

    def test_rejects_login_page(self):
        with self.assertRaisesRegex(RuntimeError, "login"):
            extract_article_content("<html><body>Sign in</body></html>")

    def test_extracts_current_semantic_article_markup(self):
        html = """
        <html><head>
          <meta name="description" content="A useful rubric">
          <meta property="article:section" content="Finance">
        </head><body>
          <article data-testid="Article">
            <h1>Current article</h1>
            <figure><img alt="Lead image" src="https://www.economist.com/cdn-cgi/image/width=960/content-assets/images/lead.jpg"></figure>
            <p data-component="paragraph">First <strong>paragraph</strong>.</p>
            <h2>A crosshead</h2>
            <p data-component="paragraph">Second paragraph.</p>
          </article>
        </body></html>
        """
        content = extract_article_content(html)
        self.assertEqual(content["headline"], "Current article")
        self.assertEqual(content["section"]["name"], "Finance")
        self.assertEqual(
            [block["type"] for block in content["body"]],
            ["IMAGE", "TEXT", "CROSSHEAD", "TEXT"],
        )
        self.assertEqual(content["body"][0]["alt"], "Lead image")
        self.assertIn("<strong>paragraph</strong>", content["body"][1]["textHtml"])


class ImageTypeTests(unittest.TestCase):
    def test_magic_bytes_override_incorrect_content_type(self):
        self.assertEqual(
            _image_extension(b"\xff\xd8\xffmock-jpeg", "image/png"), ".jpg"
        )

    def test_detects_png(self):
        self.assertEqual(_image_extension(b"\x89PNG\r\n\x1a\nmock"), ".png")


if __name__ == "__main__":
    unittest.main()
