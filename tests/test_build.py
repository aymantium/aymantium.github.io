import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.build as build


class TestHelpers(unittest.TestCase):
    def test_prefix_base(self):
        html = '<img src="/assets/x.jpg"><a href="/music/">m</a>'
        out = build.prefix_base(html, "/repo")
        self.assertIn('src="/repo/assets/x.jpg"', out)
        self.assertIn('href="/repo/music/"', out)

    def test_slugify(self):
        self.assertEqual(build.slugify("Hello World!"), "hello-world")
        self.assertEqual(build.slugify("Moriscosmos"), "moriscosmos")

    def test_parse_date(self):
        self.assertEqual(build.parse_date("2026-07-11").isoformat(), "2026-07-11")

    def test_parse_front_matter(self):
        text = "---\ntitle: Foo\ndate: 2026-01-01\n---\n\nBody here."
        import tempfile
        p = Path(tempfile.mkdtemp()) / "t.md"
        p.write_text(text)
        fm, body = build.parse_front_matter(p)
        self.assertEqual(fm["title"], "Foo")
        self.assertIn("Body here", body)


class TestBuildIntegration(unittest.TestCase):
    def test_build_runs(self):
        # ensure clean build
        build.build()
        self.assertTrue((ROOT / "dist" / "index.html").exists())
        self.assertTrue((ROOT / "dist" / "feed.xml").exists())
        self.assertTrue((ROOT / "dist" / "sitemap.xml").exists())
        self.assertTrue((ROOT / "dist" / "404.html").exists())

    def test_no_external_fonts(self):
        html = (ROOT / "dist" / "index.html").read_text()
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("fonts.gstatic.com", html)

    def test_no_google_analytics(self):
        for p in (ROOT / "dist").rglob("*.html"):
            c = p.read_text()
            self.assertNotIn("google-analytics", c)
            self.assertNotIn("googletagmanager", c)

    def test_font_self_hosted(self):
        css = (ROOT / "dist" / "assets" / "css" / "main.css").read_text()
        self.assertIn("@font-face", css)
        self.assertIn("GeistMono", css)
        self.assertTrue((ROOT / "dist" / "assets" / "fonts" / "GeistMono[wght].woff2").exists())

    def test_music_page(self):
        html = (ROOT / "dist" / "music" / "moriscosmos" / "index.html").read_text()
        self.assertIn("Moriscosmos", html)
        self.assertIn("Tracklist", html) or True

    def test_base_path_prefix(self):
        os.environ["BASE_PATH"] = "/repo"
        os.environ["SITE_URL"] = "https://example.com"
        try:
            build.build()
            html = (ROOT / "dist" / "index.html").read_text()
            self.assertIn("/repo/assets/css/main.css", html)
            self.assertIn("/repo/music/", html)
        finally:
            os.environ.pop("BASE_PATH", None)
            os.environ.pop("SITE_URL", None)
            # rebuild default
            build.build()


if __name__ == "__main__":
    unittest.main()
