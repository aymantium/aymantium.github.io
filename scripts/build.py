#!/usr/bin/env python3
"""Static site generator for Aymantium."""

import os
import re
import shutil
import sys
import urllib.parse
from datetime import date, datetime
from pathlib import Path

import jinja2
import markdown as md
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content"
TEMPLATES = ROOT / "templates"
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"

BASE_PATH = os.environ.get("BASE_PATH", "").rstrip("/")
SITE_URL = os.environ.get("SITE_URL", "https://aymantium.github.io").rstrip("/")
DRAFTS = os.environ.get("DRAFTS", "").lower() in ("1", "true", "yes")
BUILD_ERRORS = []


def fail(msg):
    BUILD_ERRORS.append(msg)
    print("ERROR:", msg, file=sys.stderr)


def slugify(value):
    value = str(value).strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "item"


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(value.strip()).date()
        except ValueError:
            pass
    return None


def parse_front_matter(path):
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm_raw = parts[1]
            try:
                fm = yaml.safe_load(fm_raw) or {}
            except yaml.YAMLError as exc:
                fail(f"{path}: invalid YAML front matter: {exc}")
                fm = {}
            body = parts[2].lstrip("\n")
            return fm, body
    return {}, text


REQUIRED = {
    "music": ["title", "date"],
    "art": ["title", "date"],
    "writing": ["title", "date"],
    "library": ["title", "date"],
    "pages": ["title"],
}


def normalize_tags(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    fail(f"tags must be a list, got {type(value).__name__}")
    return []



def image_dimensions(path):
    """Return (width, height) for a local image file, or (None, None)."""
    try:
        data = path.read_bytes()
    except OSError:
        return None, None
    # PNG
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        import struct
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    # GIF
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        import struct
        w, h = struct.unpack("<HH", data[6:10])
        return int(w), int(h)
    # JPEG
    if data.startswith(b"\xff\xd8"):
        i = 2
        n = len(data)
        import struct
        while i < n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i+1]
            if marker in (0xD8, 0xD9):
                i += 2
                continue
            if marker == 0xDA:
                break
            if i + 4 > n:
                break
            seglen = struct.unpack(">H", data[i+2:i+4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if i + 9 <= n:
                    h = struct.unpack(">H", data[i+5:i+7])[0]
                    w = struct.unpack(">H", data[i+7:i+9])[0]
                    return int(w), int(h)
            i += 2 + seglen
    return None, None


def normalize_images(value, title):
    out = []
    if not value:
        return out
    if not isinstance(value, list):
        fail("images must be a list")
        return out
    for item in value:
        if isinstance(item, str):
            w, h = 1200, 800
            if str(item).startswith("/"):
                dw, dh = image_dimensions(ROOT / str(item).lstrip("/"))
                if dw and dh:
                    w, h = dw, dh
            out.append({"src": item, "alt": title, "caption": "", "width": w, "height": h})
        elif isinstance(item, dict):
            src = item.get("src") or item.get("url")
            if not src:
                fail("image missing src")
                continue
            alt = item.get("alt") or title
            w = item.get("width")
            h = item.get("height")
            if not w or not h:
                if str(src).startswith("/"):
                    dw, dh = image_dimensions(ROOT / str(src).lstrip("/"))
                    if dw and dh:
                        w = w or dw
                        h = h or dh
            if not w:
                w = 1200
            if not h:
                h = 800
            out.append({
                "src": src,
                "alt": alt,
                "caption": item.get("caption", "") or "",
                "width": w,
                "height": h,
            })
        else:
            fail(f"invalid image entry: {item}")
    return out


def read_content():
    items = {"music": [], "art": [], "writing": [], "library": [], "pages": []}
    if not CONTENT.exists():
        return items
    for section in items:
        section_dir = CONTENT / section
        if not section_dir.exists():
            continue
        for path in sorted(section_dir.glob("*.md")):
            fm, body = parse_front_matter(path)
            # required
            for field in REQUIRED.get(section, []):
                if field not in fm or fm.get(field) in (None, ""):
                    fail(f"{path}: missing required field '{field}'")
            title = fm.get("title", path.stem)
            slug = slugify(fm.get("slug", path.stem))
            # duplicate check later
            d = parse_date(fm.get("date")) if section != "pages" else None
            if section != "pages" and d is None:
                fail(f"{path}: invalid or missing date '{fm.get('date')}'")
            draft = bool(fm.get("draft", False))
            tags = normalize_tags(fm.get("tags"))
            body = re.sub(r"^#\s+" + re.escape(str(title)) + r"\s*\n+", "", body, count=1)
            body_html = md.markdown(body, extensions=["extra", "fenced_code", "sane_lists", "smarty"])
            body_html = prefix_base(body_html, BASE_PATH)
            reading_time = None
            if section == "writing":
                words = len(re.sub(r"<[^>]+>", " ", body).split())
                reading_time = max(1, round(words / 200))
            item = {
                "section": section,
                "slug": slug,
                "title": title,
                "date": d,
                "date_str": d.isoformat() if d else "",
                "updated": parse_date(fm.get("updated")) if fm.get("updated") else None,
                "updated_str": (parse_date(fm.get("updated")).isoformat() if fm.get("updated") and parse_date(fm.get("updated")) else ""),
                "draft": draft,
                "tags": tags,
                "body_md": body,
                "body_html": body_html,
                "reading_time": reading_time,
                "_path": str(path),
            }
            # section-specific
            if section == "music":
                item["type"] = fm.get("type", "release")
                item["cover"] = fm.get("cover")
                item["tracklist"] = fm.get("tracklist") or []
                item["credits"] = fm.get("credits")
                item["recording"] = fm.get("recording")
                item["links"] = fm.get("links") or {}
                item["description"] = fm.get("description") or ""
                item["images"] = []
            elif section == "art":
                item["medium"] = fm.get("medium") or fm.get("category")
                item["images"] = normalize_images(fm.get("images"), title)
                item["cover"] = (item["images"][0]["src"] if item["images"] else fm.get("cover"))
                item["description"] = fm.get("description") or ""
                item["links"] = fm.get("links") or {}
            elif section == "writing":
                item["description"] = fm.get("description") or fm.get("excerpt") or ""
                item["categories"] = normalize_tags(fm.get("categories"))
                item["tags"] = tags
            elif section == "library":
                item["creator"] = fm.get("creator") or fm.get("author")
                item["category"] = fm.get("category")
                item["description"] = fm.get("description") or ""
                item["url"] = fm.get("url")
            elif section == "pages":
                item["description"] = fm.get("description") or ""
            items[section].append(item)
    return items


def prefix_base(html, base):
    if not base:
        return html
    def repl(m):
        # m.group(1) is src= or href=, group(2) quote, group(3) path
        return f'{m.group(1)}{m.group(2)}{base}{m.group(3)}{m.group(4)}'
    # src="/..." or href="/..." (not //)
    html = re.sub(r'(src|href)(=)(["\'])(/(?!/)[^"\']*)(["\'])', lambda m: f'{m.group(1)}{m.group(2)}{m.group(3)}{base}{m.group(4)}{m.group(5)}', html)
    return html


def u(path):
    if not path:
        return ""
    if isinstance(path, str) and (path.startswith("http://") or path.startswith("https://") or path.startswith("#")):
        return path
    if isinstance(path, str) and path.startswith("/"):
        return BASE_PATH + path
    return path


def validate(items):
    # duplicate slugs per section
    for section, lst in items.items():
        seen = {}
        for it in lst:
            if it["slug"] in seen:
                fail(f"duplicate slug '{it['slug']}' in {section}: {it['_path']} and {seen[it['slug']]}")
            seen[it["slug"]] = it["_path"]
    # duplicate urls
    urls = {}
    for section, lst in items.items():
        for it in lst:
            if section == "pages":
                url = "/" + slugify(it["title"]) + "/" if False else None
            else:
                url = f"/{section}/{it['slug']}/"
            if url in urls:
                fail(f"duplicate url {url}")
            urls[url] = it["_path"]
    # images existence
    for section, lst in items.items():
        for it in lst:
            for key in ("cover",):
                v = it.get(key)
                if isinstance(v, str) and v.startswith("/"):
                    if not (ROOT / v.lstrip("/")).exists():
                        fail(f"missing image: {v} ({it['_path']})")
            for img in it.get("images", []):
                src = img.get("src")
                if isinstance(src, str) and src.startswith("/"):
                    if not (ROOT / src.lstrip("/")).exists():
                        fail(f"missing image: {src} ({it['_path']})")
    # tags slug check
    # broken internal refs not implemented


def url_for(section, slug):
    return f"/{section}/{slug}/"


def build():
    global BUILD_ERRORS, BASE_PATH, SITE_URL, DRAFTS
    BASE_PATH = os.environ.get("BASE_PATH", "").rstrip("/")
    SITE_URL = os.environ.get("SITE_URL", "https://aymantium.github.io").rstrip("/")
    DRAFTS = os.environ.get("DRAFTS", "").lower() in ("1", "true", "yes")
    BUILD_ERRORS = []
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    # copy assets
    if ASSETS.exists():
        shutil.copytree(ASSETS, DIST / "assets")
    items = read_content()
    validate(items)
    if BUILD_ERRORS:
        print("Build aborted due to errors:", file=sys.stderr)
        for e in BUILD_ERRORS:
            print(" -", e, file=sys.stderr)
        sys.exit(1)

    # filter drafts
    def include(it):
        return (not it["draft"]) or DRAFTS

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        autoescape=jinja2.select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["u"] = u
    env.filters["slug"] = slugify
    env.globals["base_path"] = BASE_PATH

    # sorted entries
    for section in ("music", "art", "writing", "library"):
        items[section] = sorted([i for i in items[section] if include(i)], key=lambda x: x["date"], reverse=True)

    # assign urls
    for section in ("music", "art", "writing", "library"):
        for it in items[section]:
            it["url"] = url_for(section, it["slug"])
    for it in items["pages"]:
        if include(it):
            it["url"] = "/" + slugify(it["title"]) + "/"

    # music prev/next (chronological: next newer? We'll set prev=older, next=newer based on date asc)
    def attach_nav(lst):
        # lst currently newest first
        asc = list(reversed(lst))
        for idx, it in enumerate(asc):
            it["prev"] = asc[idx - 1] if idx > 0 else None
            it["next"] = asc[idx + 1] if idx < len(asc) - 1 else None
    attach_nav(items["music"])
    attach_nav(items["art"])
    attach_nav(items["writing"])

    # render helper
    def render(template, context, out_path):
        t = env.get_template(template)
        html = t.render(**context)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")

    context_common = {
        "base_path": BASE_PATH,
        "rss_url": f"{BASE_PATH}/feed.xml",
    }

    # home
    recent_releases = items["music"][:4]
    recent_writing = items["writing"][:4]
    recent_art = items["art"][:2]
    announcements = []
    # announcements from content? none
    render("home.html", {
        **context_common,
        "title": None,
        "description": "Personal archive of Aymantium.",
        "recent_releases": recent_releases,
        "recent_writing": recent_writing,
        "recent_art": recent_art,
        "announcements": announcements,
    }, DIST / "index.html")

    # music archive + pages
    render("music.html", {**context_common, "title": "Music", "entries": items["music"]}, DIST / "music" / "index.html")
    for r in items["music"]:
        render("release.html", {**context_common, "title": r["title"], "description": r.get("description"), **r}, DIST / r["url"].strip("/") / "index.html")
    # art
    render("art.html", {**context_common, "title": "Art", "entries": items["art"]}, DIST / "art" / "index.html")
    for a in items["art"]:
        render("artwork.html", {**context_common, "title": a["title"], **a}, DIST / a["url"].strip("/") / "index.html")
    # writing
    render("writing.html", {**context_common, "title": "Writing", "entries": items["writing"]}, DIST / "writing" / "index.html")
    for a in items["writing"]:
        render("article.html", {**context_common, "title": a["title"], "description": a.get("description"), **a}, DIST / a["url"].strip("/") / "index.html")
    # library
    render("library.html", {**context_common, "title": "Library", "entries": items["library"]}, DIST / "library" / "index.html")
    for e in items["library"]:
        render("page.html", {**context_common, "title": e["title"], **e}, DIST / e["url"].strip("/") / "index.html")
    # pages (about)
    for p in items["pages"]:
        if not include(p):
            continue
        slug = slugify(p["title"])
        tmpl = "about.html" if slug == "about" else "page.html"
        out = DIST / slug / "index.html" if slug != "about" else DIST / "about" / "index.html"
        # normalize about path
        if slug == "about":
            out = DIST / "about" / "index.html"
        else:
            out = DIST / slug / "index.html"
        render(tmpl, {**context_common, "title": p["title"], **p}, out)
    # ensure about exists even if no content
    if not any(slugify(p["title"]) == "about" for p in items["pages"] if include(p)):
        # render default about
        render("about.html", {**context_common, "title": "About", "body_html": "<p>Independent musician and artist.</p>"}, DIST / "about" / "index.html")

    # tags
    all_tagged = []
    for section in ("music", "art", "writing", "library"):
        for it in items[section]:
            for t in it.get("tags", []):
                all_tagged.append((t, it, section))
    tags = sorted(set(t for t, _, _ in all_tagged))
    counts = {t: sum(1 for x, _, _ in all_tagged if x == t) for t in tags}
    render("tags.html", {**context_common, "title": "Tags", "tags": tags, "counts": counts}, DIST / "tags" / "index.html")
    for t in tags:
        entries = []
        for tag, it, section in all_tagged:
            if tag == t:
                e = dict(it)
                e["section"] = section
                entries.append(e)
        entries.sort(key=lambda x: x["date"], reverse=True)
        render("tag_detail.html", {**context_common, "title": f"Tag: {t}", "tag": t, "entries": entries}, DIST / "tags" / slugify(t) / "index.html")

    # search index
    search_entries = []
    for section in ("music", "art", "writing", "library"):
        for it in items[section]:
            e = {"title": it["title"], "url": it["url"], "date_str": it["date_str"], "section": section}
            search_entries.append(e)
    search_entries.sort(key=lambda x: x["date_str"], reverse=True)
    render("search.html", {**context_common, "title": "Search", "entries": search_entries}, DIST / "search" / "index.html")

    # contact
    render("contact.html", {**context_common, "title": "Contact"}, DIST / "contact" / "index.html")

    # 404
    render("404.html", {**context_common, "title": "404"}, DIST / "404.html")

    # RSS feed (writing)
    rss_items = []
    for a in items["writing"][:20]:
        link = SITE_URL + BASE_PATH + a["url"]
        rss_items.append((a, link))
    feed_xml = build_rss(rss_items, SITE_URL, BASE_PATH)
    (DIST / "feed.xml").write_text(feed_xml, encoding="utf-8")

    # sitemap
    sitemap_urls = []
    # collect all generated pages
    for path in DIST.rglob("index.html"):
        rel = path.relative_to(DIST).as_posix()
        if rel == "index.html":
            url_path = "/"
        else:
            url_path = "/" + rel.replace("index.html", "")
        sitemap_urls.append(SITE_URL + BASE_PATH + url_path)
    # include 404? no
    sitemap_xml = build_sitemap(sorted(set(sitemap_urls)))
    (DIST / "sitemap.xml").write_text(sitemap_xml, encoding="utf-8")

    # .nojekyll
    (DIST / ".nojekyll").write_text("", encoding="utf-8")

    print(f"Build complete: {DIST}")


def build_rss(items, site_url, base_path):
    from xml.etree.ElementTree import Element, SubElement, tostring
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "Aymantium"
    SubElement(channel, "link").text = site_url + base_path + "/"
    SubElement(channel, "description").text = "Personal archive of Aymantium."
    for a, link in items:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = a["title"]
        SubElement(item, "link").text = link
        SubElement(item, "guid").text = link
        SubElement(item, "pubDate").text = format_rfc822(a["date"])
        if a.get("description"):
            SubElement(item, "description").text = a["description"]
    xml = tostring(rss, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml + "\n"


def format_rfc822(d):
    # simple RFC822
    import email.utils
    dt = datetime(d.year, d.month, d.day)
    return email.utils.format_datetime(dt)


def build_sitemap(urls):
    from xml.etree.ElementTree import Element, SubElement, tostring
    urlset = Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for u in urls:
        url = SubElement(urlset, "url")
        SubElement(url, "loc").text = u
    xml = tostring(urlset, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml + "\n"


if __name__ == "__main__":
    build()
