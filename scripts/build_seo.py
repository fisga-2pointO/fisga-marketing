#!/usr/bin/env python3
"""Generate and check the crawler-facing parts of fisga.co.

Runs at deploy (see nixpacks.toml) and is safe to run locally any time:

    python3 scripts/build_seo.py

What it does, in place:
  * Fills the shared nav and footer into pages that have <!-- NAV --> / <!-- FOOTER --> markers.
  * Rebuilds FAQPage JSON-LD (<script id="faq-jsonld">) from the visible .faq-item blocks,
    so the structured data always matches the text on the page.
  * Rebuilds Article JSON-LD (<script id="article-jsonld">) for /learn articles from the
    visible H1, byline, dates and meta tags.
  * Fills the /learn article list and each article's related-article links.
  * Writes sitemap.xml and llms.txt from every page that is indexable (no noindex) and
    has a canonical URL.

Exits non-zero if any JSON-LD is invalid, a canonical does not match its URL, or a FAQ
block is malformed. Copy-rule issues on new pages are printed as warnings only.
"""
import datetime
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://www.fisga.co"
PARTIALS = os.path.join(ROOT, "scripts", "partials")
SKIP_DIRS = {".git", ".claude", "scripts", "node_modules"}

# Copy rules for visible text on new pages (warnings, not errors)
COPY_RULES = [
    ("—", "em dash"),
    ("AI-powered", '"AI-powered"'),
    ("synthetic", '"synthetic"'),
    ("simulation", '"simulation"'),
    ("Census", "named federal agency"),
    ("BLS", "named federal agency"),
    ("FRED", "named federal agency"),
    ("Bureau", "named federal agency"),
    ("CDC", "named federal agency"),
    ("USDA", "named federal agency"),
]
COPY_RULE_PATHS = ("faq.html", "methodology.html", "learn/", "about/", "case-studies/index.html")

errors, warnings = [], []


# ── helpers ────────────────────────────────────────────────────────────────

def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def write_if_changed(path, text):
    full = os.path.join(ROOT, path)
    old = open(full, encoding="utf-8").read() if os.path.exists(full) else None
    if old != text:
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"  wrote {path}")


def url_for(path):
    """File path → public URL path. index.html → /, learn/index.html → /learn, a/b.html → /a/b"""
    p = path[:-len(".html")]
    if p == "index":
        return "/"
    if p.endswith("/index"):
        p = p[:-len("/index")]
    return "/" + p


def meta(s, name, attr="name"):
    m = re.search(r'<meta\s+%s="%s"\s+content="([^"]*)"' % (attr, re.escape(name)), s)
    return html.unescape(m.group(1)) if m else None


INLINE_TAGS = r"a|abbr|b|cite|code|em|i|mark|q|s|small|span|strong|sub|sup|time|u"


def text_of(fragment):
    # Inline tags join text as-is ("<strong>$80K</strong>." → "$80K."); block tags become spaces
    t = re.sub(r"</?(?:%s)\b[^>]*>" % INLINE_TAGS, "", fragment)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def visible_text(s):
    body = s.split("<body", 1)[-1]
    body = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    return text_of(body)


def replace_region(s, name, content):
    """Replace text between <!-- NAME:START --> and <!-- NAME:END -->."""
    pat = re.compile(r"(<!-- %s:START -->)(.*?)(<!-- %s:END -->)" % (name, name), re.S)
    return pat.sub(lambda m: m.group(1) + "\n" + content.rstrip() + "\n" + m.group(3), s, count=1)


def replace_jsonld(s, script_id, data):
    pat = re.compile(r'(<script type="application/ld\+json" id="%s">)(.*?)(</script>)' % script_id, re.S)
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return pat.sub(lambda m: m.group(1) + "\n" + body + "\n" + m.group(3), s, count=1)


def full_datetime(iso):
    """2026-10-05 → 2026-10-05T12:00:00-06:00 (noon, Salt Lake City time). Google wants a timezone.
    US daylight time runs from the second Sunday of March to the first Sunday of November.
    Computed here so the build does not depend on the system timezone database."""
    if "T" in iso:
        return iso
    d = datetime.date.fromisoformat(iso)
    def nth_sunday(month, n):
        first = datetime.date(d.year, month, 1)
        return first + datetime.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))
    offset = "-06:00" if nth_sunday(3, 2) <= d < nth_sunday(11, 1) else "-07:00"
    return f"{iso}T12:00:00{offset}"


def human_date(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


# ── discovery ──────────────────────────────────────────────────────────────

def all_pages():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".html") and not fn.startswith("google"):
                out.append(os.path.relpath(os.path.join(dirpath, fn), ROOT))
    return sorted(out)


def page_info(path, s):
    robots = (meta(s, "robots") or "").lower()
    canon = re.search(r'<link rel="canonical" href="([^"]+)"', s)
    title = re.search(r"<title>(.*?)</title>", s, re.S)
    h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", s, re.S)
    pub = re.search(r'<time class="published" datetime="([^"]+)"', s)
    upd = re.search(r'<time class="updated" datetime="([^"]+)"', s)
    return {
        "path": path,
        "url": url_for(path),
        "indexable": "noindex" not in robots,
        "canonical": canon.group(1) if canon else None,
        "title": text_of(title.group(1)) if title else path,
        "h1": text_of(h1.group(1)) if h1 else None,
        "description": meta(s, "description") or "",
        "llms": meta(s, "llms-description"),
        "card": meta(s, "fisga:card-title"),
        "published": pub.group(1) if pub else meta(s, "article:published_time", "property"),
        "updated": (upd.group(1) if upd else None) or meta(s, "article:modified_time", "property"),
        "image": meta(s, "og:image", "property"),
        "type": meta(s, "fisga:type"),
        "related": [x.strip() for x in (meta(s, "fisga:related") or "").split(",") if x.strip()],
    }


# ── generators ─────────────────────────────────────────────────────────────

def build_nav(s, url):
    nav = open(os.path.join(PARTIALS, "nav.html"), encoding="utf-8").read()
    # Mark the current section for screen readers and styling
    section = "/" + url.strip("/").split("/")[0] if url != "/" else "/"
    nav = nav.replace(f'href="{section}"', f'href="{section}" aria-current="page"', 1) if section != "/" else nav
    return replace_region(s, "NAV", nav)


def build_footer(s):
    foot = open(os.path.join(PARTIALS, "footer.html"), encoding="utf-8").read()
    foot = foot.replace("{{YEAR}}", str(datetime.date.today().year))
    return replace_region(s, "FOOTER", foot)


FAQ_ITEM = re.compile(
    r'<div class="faq-item[^"]*">\s*<(h[2-4]|p) class="faq-q">(.*?)</\1>\s*<div class="faq-a">(.*?)</div>\s*</div>',
    re.S,
)


def build_faq(path, s):
    items = FAQ_ITEM.findall(s)
    declared = len(re.findall(r'<div class="faq-item', s))
    if declared != len(items):
        errors.append(f"{path}: found {declared} .faq-item blocks but could only read {len(items)}; "
                      f"keep the markup as <div class=\"faq-item\"><h3 class=\"faq-q\">…</h3><div class=\"faq-a\">…</div></div>")
    if not items:
        errors.append(f"{path}: has a faq-jsonld block but no visible FAQ items")
        return s
    data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": text_of(q),
             "acceptedAnswer": {"@type": "Answer", "text": text_of(a)}}
            for _, q, a in items
        ],
    }
    return replace_jsonld(s, "faq-jsonld", data)


def build_article(info, s):
    author = re.search(r'<a rel="author" href="([^"]+)"[^>]*>(.*?)</a>', s, re.S)
    for key in ("h1", "published", "canonical"):
        if not info[key]:
            errors.append(f"{info['path']}: article is missing {key}")
            return s
    if not author:
        errors.append(f"{info['path']}: article is missing the author byline link (<a rel=\"author\" …>)")
        return s
    author_url = SITE + author.group(1) if author.group(1).startswith("/") else author.group(1)
    data = {
        "@context": "https://schema.org",
        "@type": "Article",
        "@id": info["canonical"] + "#article",
        "headline": info["h1"],
        "description": info["description"],
        "url": info["canonical"],
        "mainEntityOfPage": info["canonical"],
        "datePublished": full_datetime(info["published"]),
        "dateModified": full_datetime(info["updated"] or info["published"]),
        "author": {"@type": "Person", "@id": author_url + "#person",
                   "name": text_of(author.group(2)), "url": author_url},
        "publisher": {"@id": SITE + "/#organization", "@type": "Organization", "name": "Fisga",
                      "logo": {"@type": "ImageObject", "url": SITE + "/fisga-logo.png"}},
        "inLanguage": "en-US",
    }
    if info["image"]:
        data["image"] = info["image"]
    return replace_jsonld(s, "article-jsonld", data)


def article_card(a):
    date = human_date(a["published"]) if a["published"] else ""
    return (f'  <a class="card" href="{a["url"]}">\n'
            f'    <span class="card-tag">{html.escape(date)}</span>\n'
            f'    <span class="card-title">{html.escape(a["h1"] or a["title"])}</span>\n'
            f'    <span class="card-text">{html.escape(a["description"])}</span>\n'
            f'    <span class="card-cta">Read the answer &rarr;</span>\n'
            f'  </a>')


def build_learn_index(s, articles):
    if not articles:
        body = '<p class="empty">The first articles are on their way. In the meantime, see the <a href="/faq">FAQ</a> or the <a href="/case-studies">case studies</a>.</p>'
    else:
        body = '<div class="card-grid">\n' + "\n".join(article_card(a) for a in articles) + "\n</div>"
    return replace_region(s, "LEARN-INDEX", body)


def build_related(info, s, articles):
    by_slug = {a["url"].rsplit("/", 1)[-1]: a for a in articles}
    chosen = [by_slug[x] for x in info["related"] if x in by_slug and by_slug[x]["url"] != info["url"]]
    for x in info["related"]:
        if x not in by_slug:
            warnings.append(f"{info['path']}: related article '{x}' not found (or not indexable yet)")
    if not chosen:  # fall back to the newest other articles
        chosen = [a for a in articles if a["url"] != info["url"]][:3]
    if not chosen:
        body = '<p class="muted">More answers are coming soon. Browse <a href="/learn">all articles</a> or the <a href="/faq">FAQ</a>.</p>'
    else:
        body = '<div class="card-grid">\n' + "\n".join(article_card(a) for a in chosen[:3]) + "\n</div>"
    return replace_region(s, "RELATED", body)


def build_sitemap(pages):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<!-- Generated by scripts/build_seo.py. Do not edit by hand. -->',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in pages:
        lines.append("  <url>")
        lines.append(f"    <loc>{html.escape(p['canonical'])}</loc>")
        lastmod = p["updated"] or p["published"]
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


LLMS_HEADER = """# Fisga

> Fisga is a decision intelligence and market research platform for CPG brands, operators and founders. It answers pricing, positioning, feasibility, concept testing and segmentation questions in minutes, grounded in U.S. federal data. Fisga is based in Salt Lake City, Utah, and was founded by Eduardo Henriques.

Every Fisga finding traces to a named public government dataset. Studies typically run in under 20 minutes, compared with six to eight weeks for traditional research. Contact: hello@fisga.co.
"""

LLMS_SECTIONS = [
    ("Start here", lambda u: u in ("/", "/faq", "/methodology", "/case-studies") or u.startswith("/about/")),
    ("Case studies", lambda u: u.startswith("/case-studies/")),
    ("Learn", lambda u: u == "/learn" or u.startswith("/learn/")),
    ("Optional", lambda u: True),
]


def build_llms(pages):
    out = [LLMS_HEADER]
    used = set()
    for name, match in LLMS_SECTIONS:
        rows = []
        for p in pages:
            if p["url"] in used or not match(p["url"]):
                continue
            used.add(p["url"])
            label = p["card"] or p["h1"] or p["title"]
            desc = (p["llms"] or p["description"]).strip()
            rows.append(f"- [{label}]({p['canonical']}): {desc}")
        if rows:
            out.append(f"## {name}\n\n" + "\n".join(rows) + "\n")
    return "\n".join(out)


# ── checks ─────────────────────────────────────────────────────────────────

def check_page(info, s):
    path = info["path"]
    for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', s, re.S):
        try:
            json.loads(m.group(1))
        except json.JSONDecodeError as e:
            errors.append(f"{path}: invalid JSON-LD ({e})")
    if "PLACEHOLDER" in s and "application/ld+json" in s:
        warnings.append(f"{path}: contains PLACEHOLDER values (fill in before going live)")
    if info["indexable"]:
        if not info["canonical"]:
            warnings.append(f"{path}: indexable but has no canonical tag, so it is left out of the sitemap")
        else:
            want = SITE + ("/" if info["url"] == "/" else info["url"])
            if info["canonical"] != want:
                errors.append(f"{path}: canonical is {info['canonical']}, expected {want}")
    if path.startswith(COPY_RULE_PATHS):
        vis = visible_text(s) + " " + (info["description"] or "")
        for needle, label in COPY_RULES:
            if needle in vis:
                warnings.append(f"{path}: copy rule, contains {label}")


# ── main ───────────────────────────────────────────────────────────────────

def main():
    print("build_seo: scanning pages")
    paths = all_pages()
    sources = {p: read(p) for p in paths}
    infos = {p: page_info(p, sources[p]) for p in paths}

    articles = sorted(
        (i for i in infos.values()
         if i["type"] == "article" and i["indexable"] and not os.path.basename(i["path"]).startswith("_")),
        key=lambda i: (i["published"] or ""), reverse=True)

    for p in paths:
        s, info = sources[p], infos[p]
        if "<!-- NAV:START -->" in s:
            s = build_nav(s, info["url"])
        if "<!-- FOOTER:START -->" in s:
            s = build_footer(s)
        if 'id="faq-jsonld"' in s:
            s = build_faq(p, s)
        if info["type"] == "article" and 'id="article-jsonld"' in s:
            s = build_article(info, s)
        if "<!-- RELATED:START -->" in s:
            s = build_related(info, s, articles)
        if "<!-- LEARN-INDEX:START -->" in s:
            s = build_learn_index(s, articles)
        check_page(info, s)
        if s != sources[p]:
            write_if_changed(p, s)

    public = [i for i in infos.values() if i["indexable"] and i["canonical"]]
    public.sort(key=lambda i: (i["url"] != "/", i["url"].count("/"), i["url"]))
    write_if_changed("sitemap.xml", build_sitemap(public))
    llms = build_llms(public)
    for needle, label in COPY_RULES:
        if needle in llms:
            warnings.append(f"llms.txt: copy rule, contains {label} (set a <meta name=\"llms-description\"> on that page)")
    write_if_changed("llms.txt", llms)
    print(f"build_seo: {len(public)} public pages, {len(articles)} learn articles")

    for w in warnings:
        print("  WARNING", w)
    for e in errors:
        print("  ERROR", e)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
