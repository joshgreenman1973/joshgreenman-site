#!/usr/bin/env python3
"""
Refresh the auto-generated list in index.html.

One block is machine-written; everything else on the page is hand-written and
is never touched:

  <!-- AUTO:ARCHIVE START -->   every piece and tool, newest first, by year

Sources:
  data/archive-static.json Daily News, Sun, Post, Politico and Slate pieces (fixed)
  Substack archive API     https://joshgreenman.substack.com/api/v1/archive
  Vital City Ghost API     https://vital-city.ghost.io/ghost/api/content/posts/
  data/tools.json          hand-picked tools that always appear
  Experiments manifest     the newest few tools, read from each one's own
                           <title> and <meta name="description">
  shots/<slug>.jpg         screenshots for hover previews, if present

    python3 build.py           rebuild the list
    python3 build.py --shots   also screenshot any listed tool that has no
                               shot yet (needs Google Chrome; run on the Mac)

Fails loudly. If a source returns nothing, or too little to be plausible, the
script exits non-zero and writes nothing, rather than quietly publishing an
empty page.

    python3 build.py
"""

import html
import itertools
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")
OVERRIDES = os.path.join(HERE, "data", "overrides.json")
CACHE = os.path.join(HERE, "data", "substack-cache.json")
STATIC = os.path.join(HERE, "data", "archive-static.json")
TOOLS = os.path.join(HERE, "data", "tools.json")
SHOTS = os.path.join(HERE, "shots")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

SUBSTACK = "https://joshgreenman.substack.com/api/v1/archive?sort=new&limit=50"
GHOST_KEY = "dd8e178e9ddfc883537e71dd07"
GHOST = (
    "https://vital-city.ghost.io/ghost/api/content/posts/"
    "?key=" + GHOST_KEY + "&limit=50&order=published_at%20desc"
    "&filter=authors.slug:greenman-josh"
)
MANIFEST = (
    "https://raw.githubusercontent.com/joshgreenman1973/experiments/"
    "main/projects-manifest.json"
)
EXPERIMENTS_PAGES = "https://joshgreenman1973.github.io/experiments/"

NEW_EXPERIMENTS = 4        # newest tools added to the hand-picked ones
MIN_WRITING = 6            # fewer than this from Substack + Vital City means a source broke
MIN_STATIC = 300           # the fixed archive should never shrink below this
UA = "joshgreenman.com site builder (+https://joshgreenman.com)"

AP_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June",
             "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------

def get(url, as_json=True):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=45) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw) if as_json else raw


def die(msg):
    sys.stderr.write("BUILD FAILED: " + msg + "\n")
    sys.exit(1)


# --------------------------------------------------------------------------
# text
# --------------------------------------------------------------------------

def smarten(s):
    """
    Curly quotes, per the house style of the page. The sources mostly hand
    these over already curled; this catches the ones that arrive straight.
    """
    s = s.replace("\u2026", "...").replace("\xa0", " ").strip()
    # doubles: an opening quote after the start, whitespace or a bracket
    s = re.sub(r'(^|[\s([{])"', "\\1\u201c", s)
    s = s.replace('"', "\u201d")
    # singles: an apostrophe after a letter or digit, an opening quote otherwise
    s = re.sub(r"(?<=[A-Za-z0-9])'", "\u2019", s)
    s = re.sub(r"(^|[\s([{])'", "\\1\u2018", s)
    return s.replace("'", "\u2019")


def undash(s):
    """
    No em dashes in visible text. A matched pair becomes parentheses; a lone
    dash becomes a comma when a conjunction follows it and a colon otherwise.
    """
    s = s.replace("—", "–")
    parts = s.split("–")
    if len(parts) == 3:                       # a — b — c  ->  a (b) c
        a, b, c = (p.strip() for p in parts)
        return (a + " (" + b + ") " + c).replace("  ", " ").strip()
    while "–" in s:
        head, tail = s.split("–", 1)
        nxt = tail.strip().split(" ")[0].lower().strip(",.")
        joiner = ", " if nxt in ("and", "but", "or", "so", "while",
                                 "then", "yet", "nor") else ": "
        s = head.rstrip().rstrip(",:;") + joiner + tail.strip()
    return s


def sentence_case(title, cfg):
    """
    Down-case a publication's title-case headline into the page's sentence
    case, protecting proper nouns. Anything it gets wrong can be pinned by
    hand in data/overrides.json rather than by editing this function.
    """
    title = smarten(title)
    if title in cfg["title_overrides"]:
        return cfg["title_overrides"][title]

    # Protect multi-word proper nouns first: "New York City", "Daily News".
    slots = []
    for phrase in sorted(cfg["phrases"], key=len, reverse=True):
        pattern = re.compile(re.escape(phrase), re.I)

        def stash(m, keep=phrase):
            slots.append(keep)
            return "\x00%d\x00" % (len(slots) - 1)

        title = pattern.sub(stash, title)

    # keyed on a straight-apostrophe form so "I’ve" still matches "I've"
    def flat(w):
        return w.replace("’", "'").replace("‘", "'").lower()

    names = {flat(n): n for n in cfg["names"]}
    acronyms = {a.upper() for a in cfg["acronyms"]}

    out = []
    start_of_sentence = True
    for tok in re.split(r"(\s+)", title):
        if not tok.strip():
            out.append(tok)
            continue
        if "\x00" in tok:
            out.append(tok)
            start_of_sentence = False
            continue

        core = tok.strip("(){}[]\"'“”‘’.,;:!?")
        bare = re.sub(r"['’]s$", "", core)

        if core.upper() in acronyms:
            word = tok.replace(core, core.upper())
        elif flat(bare) in names:
            keep = names[flat(bare)]
            word = tok.replace(core, keep + core[len(bare):])
        elif start_of_sentence:
            word = tok[:1].upper() + tok[1:] if tok[:1].isalpha() else tok
            # a leading bracket or quote shifts which character starts the word
            if not tok[:1].isalpha():
                m = re.search(r"[A-Za-z]", tok)
                if m:
                    i = m.start()
                    word = tok[:i] + tok[i].upper() + tok[i + 1:].lower()
        else:
            word = tok.lower()

        out.append(word)
        start_of_sentence = bool(re.search(r"[.?!:][\"”’]?$", tok))

    title = "".join(out)
    for i, phrase in enumerate(slots):
        title = title.replace("\x00%d\x00" % i, phrase)
    return title.strip()


def esc(s):
    return html.escape(s, quote=True)


def ap_date(iso):
    """'2026-10-07' -> 'Oct. 7' (the year heads the group)."""
    return AP_MONTHS[int(iso[5:7]) - 1] + " " + str(int(iso[8:10]))


def first_sentence(s, limit=220):
    s = re.sub(r"\s+", " ", s or "").strip()
    m = re.match(r"(.{40,}?[.?!])(\s|$)", s)
    s = m.group(1) if m else s
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "..."


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------

def substack_posts():
    """
    Substack answers this machine but blocks GitHub's runners outright: every
    endpoint and user agent gets a 403 from an Azure address. So the live fetch
    is best-effort, and each success is cached to data/substack-cache.json for
    the cloud job to read. Only a live fetch refreshes that file, which is why
    the same script also runs from Josh's Mac.
    """
    live = None
    try:
        got = get(SUBSTACK)
        if isinstance(got, list) and got:
            live = got
        else:
            sys.stderr.write("  Substack returned an empty archive\n")
    except (urllib.error.URLError, ValueError) as e:
        sys.stderr.write("  Substack unreachable from here (%s)\n" % e)

    if live is not None:
        keep = [{k: p.get(k) for k in
                 ("title", "subtitle", "description", "canonical_url",
                  "post_date", "type")}
                for p in live]
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump({"source": SUBSTACK, "newest": keep[0]["post_date"][:10],
                       "posts": keep}, f, indent=1, ensure_ascii=False)
            f.write("\n")
        print("substack: %d posts live, cache refreshed" % len(keep))
        return live

    if not os.path.exists(CACHE):
        die("Substack unreachable and no data/substack-cache.json to fall back on.")
    with open(CACHE, encoding="utf-8") as f:
        cached = json.load(f)
    posts = cached.get("posts") or []
    if not posts:
        die("data/substack-cache.json holds no posts.")
    print("substack: falling back to cache, newest %s" % cached.get("newest"))
    return posts


def collect_writing(cfg):
    sub = substack_posts()

    try:
        vc = get(GHOST).get("posts", [])
    except (urllib.error.URLError, ValueError) as e:
        die("Vital City Ghost API unreachable: %s" % e)
    if not vc:
        die("Vital City returned no posts for greenman-josh.")

    skip = [re.compile(p, re.I) for p in cfg["skip_titles"]]
    items = []

    for p in vc:
        t = smarten(p.get("title") or "")
        if not t or any(r.search(t) for r in skip):
            continue
        items.append({
            "title": t,
            "dek": smarten(p.get("custom_excerpt")
                           or first_sentence(p.get("excerpt") or "")),
            "url": p.get("url") or "",
            "date": (p.get("published_at") or "")[:10],
            "outlet": "Vital City",
        })

    for p in sub:
        if p.get("type") not in (None, "newsletter"):
            continue
        t = smarten(p.get("title") or "")
        if not t or any(r.search(t) for r in skip):
            continue
        items.append({
            "title": t,
            "dek": smarten(p.get("subtitle") or p.get("description") or ""),
            "url": p.get("canonical_url") or "",
            "date": (p.get("post_date") or "")[:10],
            "outlet": "Substack",
        })

    # A piece that ran in Vital City and was mirrored on Substack is one piece.
    # Vital City is the outlet of record, so it claims the slot no matter which
    # copy carries the later timestamp; the Substack mirror is then dropped.
    def key_of(it):
        return re.sub(r"[^a-z0-9]+", "", it["title"].lower())[:60]

    seen, deduped = set(), []
    for it in sorted(items, key=lambda i: i["outlet"] != "Vital City"):
        if not it["url"] or not it["date"]:
            continue
        key = key_of(it)
        if key in seen:
            continue
        seen.add(key)
        it["title"] = sentence_case(it["title"], cfg)
        it["dek"] = cfg["dek_overrides"].get(it["title"], undash(it["dek"]))
        deduped.append(it)
    deduped.sort(key=lambda i: i["date"], reverse=True)

    if len(deduped) < MIN_WRITING:
        die("only %d pieces after dedupe, expected at least %d"
            % (len(deduped), MIN_WRITING))
    return deduped


# --------------------------------------------------------------------------
# experiments
# --------------------------------------------------------------------------

def split_title(t):
    """'Orrery - the music of the spheres' -> 'Orrery'."""
    t = smarten(t)
    for sep in (" — ", " – ", " - ", ": "):
        if sep in t:
            head = t.split(sep)[0].strip()
            if len(head) >= 4:
                return head
    return t


def page_meta(url):
    """The project's own <title> and description. None if either is missing."""
    try:
        raw = get(url, as_json=False)
    except (urllib.error.URLError, ValueError, UnicodeError):
        return None
    t = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    d = re.search(r"<meta[^>]+name=(['\"])description\1[^>]*content=(['\"])(.*?)\2",
                  raw, re.S | re.I)
    if not t or not d:
        return None
    title = split_title(html.unescape(re.sub(r"\s+", " ", t.group(1))))
    dek = undash(smarten(html.unescape(re.sub(r"\s+", " ", d.group(3)))))
    if not title or not (50 <= len(dek) <= 240) or not dek.endswith((".", "?")):
        return None
    return {"title": title, "dek": dek}


def live_url(p):
    """Where a project is live. Projects with their own repo carry
    livePagesUrl; projects that live inside the experiments repo leave it
    empty and are served from that repo's Pages site instead."""
    if p.get("livePagesUrl"):
        return p["livePagesUrl"]
    m = re.fullmatch(r"\./([\w.-]+)/index\.html", p.get("indexUrl") or "")
    return EXPERIMENTS_PAGES + m.group(1) + "/" if m else ""


def collect_experiments(cfg, already_linked):
    try:
        manifest = get(MANIFEST)
    except (urllib.error.URLError, ValueError) as e:
        die("experiments manifest unreachable: %s" % e)
    projects = manifest.get("projects") or []
    if len(projects) < 50:
        die("manifest returned only %d projects" % len(projects))

    deny = set(cfg["experiment_deny"])
    seen, candidates = set(), []
    for p in sorted(projects, key=lambda p: p.get("created") or "", reverse=True):
        url = live_url(p)
        if not url.startswith("https://joshgreenman1973.github.io/"):
            continue
        if p.get("name") in deny or p.get("audience") != "general":
            continue
        if url in seen or url.rstrip("/") in already_linked:
            continue
        seen.add(url)
        candidates.append(p)

    picked = []
    for p in candidates[:10]:
        meta = page_meta(live_url(p))
        if not meta:
            sys.stderr.write("  skipped %s (no usable title/description)\n"
                             % p.get("name"))
            continue
        picked.append({
            "url": live_url(p),
            "date": (p.get("created") or "")[:10],
            "title": cfg["experiment_titles"].get(p["name"], meta["title"]),
            "dek": cfg["experiment_deks"].get(p["name"], meta["dek"]),
        })
        if len(picked) == NEW_EXPERIMENTS:
            break

    if len(picked) < 2:
        die("found only %d publishable new experiments, expected at least 2"
            % len(picked))
    return picked


# --------------------------------------------------------------------------
# the list
# --------------------------------------------------------------------------

OUTLET_KEYS = {
    "Daily News": "dn", "Vital City": "vc", "Substack": "ss",
    "New York Sun": "other", "Washington Post": "other",
    "Politico Magazine": "other", "Slate": "other", "Tool": "tool",
}


def slug_of(url):
    """Where a tool's screenshot lives: the last part of its URL."""
    p = urlparse(url)
    parts = [x for x in p.path.split("/") if x]
    return parts[-1] if parts else (p.hostname or "tool").split(".")[0]


def collect_static():
    with open(STATIC, encoding="utf-8") as f:
        items = json.load(f).get("items") or []
    if len(items) < MIN_STATIC:
        die("data/archive-static.json holds only %d pieces" % len(items))
    for it in items:
        it["title"] = undash(smarten(it["title"]))
    return items


def collect_tools(cfg):
    with open(TOOLS, encoding="utf-8") as f:
        curated = json.load(f).get("tools") or []
    linked = {t["url"].rstrip("/") for t in curated}
    newest = collect_experiments(cfg, linked)
    tools = [{"title": t["title"], "dek": t["dek"], "url": t["url"],
              "date": t["date"]} for t in curated + newest]
    for t in tools:
        t["outlet"] = "Tool"
    return tools, newest


def merge(static, writing, tools):
    """One list, newest first. A piece listed twice (a paper that moved it to
    a new address, a Substack mirror) keeps its first, most authoritative copy."""
    seen, out = set(), []
    for it in writing + static:
        key = re.sub(r"[^a-z0-9]+", "", it["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    out += tools
    out.sort(key=lambda i: i["date"], reverse=True)
    return out


def take_shots(tools):
    """Screenshot any listed tool without one. Best-effort and Mac-only: a
    missing shot only means no hover preview for that tool."""
    if not os.path.exists(CHROME):
        print("shots: no Chrome here, skipped")
        return
    try:
        from PIL import Image
    except ImportError:
        print("shots: Pillow not installed, skipped")
        return
    os.makedirs(SHOTS, exist_ok=True)
    for t in tools:
        dest = os.path.join(SHOTS, slug_of(t["url"]) + ".jpg")
        if os.path.exists(dest):
            continue
        tmp = dest + ".png"
        try:
            subprocess.run([CHROME, "--headless=new", "--hide-scrollbars",
                            "--window-size=1280,800", "--virtual-time-budget=10000",
                            "--screenshot=" + tmp, t["url"]],
                           capture_output=True, timeout=90)
            im = Image.open(tmp).convert("RGB").crop((0, 0, 1280, 800))
            im.resize((600, 375), Image.LANCZOS).save(
                dest, "JPEG", quality=72, optimize=True, progressive=True)
            print("shots: captured " + slug_of(t["url"]))
        except Exception as e:                       # noqa: BLE001
            print("shots: could not capture %s (%s)" % (t["url"], e))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


def render_list(items):
    out = []
    for year, group in itertools.groupby(items, key=lambda i: i["date"][:4]):
        group = list(group)
        n = len(group)
        out.append('<section class="yg" data-year="%s">' % year)
        out.append('  <h2 class="yh"><span class="yy">%s</span> '
                   '<span class="yn">%d %s</span></h2>'
                   % (year, n, "item" if n == 1 else "items"))
        out.append('  <ul>')
        for it in group:
            tool = it["outlet"] == "Tool"
            shot = ""
            if tool and os.path.exists(os.path.join(SHOTS, slug_of(it["url"]) + ".jpg")):
                shot = ' data-shot="shots/%s.jpg"' % esc(slug_of(it["url"]))
            dek = undash(smarten(it.get("dek") or ""))
            out.append('    <li class="it%s" data-d="%s" data-o="%s">'
                       % (" tool" if tool else "", esc(it["date"]),
                          OUTLET_KEYS.get(it["outlet"], "other")))
            out.append('      <span class="d">%s</span>' % esc(ap_date(it["date"])))
            line = ('      <span class="t"><a href="%s" target="_blank" rel="noopener"%s>%s</a>'
                    % (esc(it["url"]), shot, esc(it["title"])))
            if dek:
                line += ('<span class="x">%s</span>' if tool
                         else '<span class="x dek" hidden>%s</span>') % esc(dek)
            out.append(line + '</span>')
            out.append('      <span class="o">%s</span>' % esc(it["outlet"]))
            out.append('    </li>')
        out.append('  </ul>')
        out.append('</section>')
    return "\n".join(out)


# --------------------------------------------------------------------------
# splice
# --------------------------------------------------------------------------

def replace_block(page, name, body):
    start = "<!-- AUTO:%s START -->" % name
    end = "<!-- AUTO:%s END -->" % name
    i, j = page.find(start), page.find(end)
    if i < 0 or j < 0 or j < i:
        die("markers for %s missing from index.html" % name)
    indent = " " * (i - page.rfind("\n", 0, i) - 1)
    body = "\n".join(indent + line if line else line
                     for line in body.split("\n"))
    return page[:i] + start + "\n" + body + "\n" + indent + page[j:]


def main():
    with open(OVERRIDES, encoding="utf-8") as f:
        cfg = json.load(f)
    with open(INDEX, encoding="utf-8") as f:
        page = f.read()

    static = collect_static()
    writing = collect_writing(cfg)
    print("writing: %d from Substack and Vital City, newest %s (%s)"
          % (len(writing), writing[0]["title"], writing[0]["date"]))
    tools, newest = collect_tools(cfg)
    print("tools: %d, newest %s" % (len(tools), ", ".join(
        "%s (%s)" % (t["title"], t["date"]) for t in newest)))
    if "--shots" in sys.argv:
        take_shots(tools)

    items = merge(static, writing, tools)
    print("list: %d items, %s to %s"
          % (len(items), items[-1]["date"][:4], items[0]["date"][:4]))

    page = replace_block(page, "ARCHIVE", render_list(items))
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(page)
    print("index.html written")


if __name__ == "__main__":
    main()
