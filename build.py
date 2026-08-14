#!/usr/bin/env python3
"""
Refresh the auto-generated blocks in index.html.

Two blocks are machine-written; everything else on the page is hand-written and
is never touched:

  <!-- AUTO:WRITING START -->          the Latest lead + the nine-item list
  <!-- AUTO:NEW-EXPERIMENTS START -->  the two newest live experiments

Sources, all public and keyless:
  Substack archive API   https://joshgreenman.substack.com/api/v1/archive
  Vital City Ghost API   https://vital-city.ghost.io/ghost/api/content/posts/
  Experiments manifest   raw projects-manifest.json from the experiments repo
  Each experiment's own <title> and <meta name="description">

Fails loudly. If a source returns nothing, or too little to be plausible, the
script exits non-zero and writes nothing, rather than quietly publishing an
empty page.

    python3 build.py
"""

import html
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")
OVERRIDES = os.path.join(HERE, "data", "overrides.json")
CACHE = os.path.join(HERE, "data", "substack-cache.json")

SUBSTACK = "https://joshgreenman.substack.com/api/v1/archive?sort=new&limit=30"
GHOST_KEY = "dd8e178e9ddfc883537e71dd07"
GHOST = (
    "https://vital-city.ghost.io/ghost/api/content/posts/"
    "?key=" + GHOST_KEY + "&limit=25&order=published_at%20desc"
    "&filter=authors.slug:greenman-josh"
)
MANIFEST = (
    "https://raw.githubusercontent.com/joshgreenman1973/experiments/"
    "main/projects-manifest.json"
)

WRITING_ITEMS = 9          # one lead plus eight list rows
NEW_EXPERIMENTS = 2
MIN_WRITING = 6            # fewer than this means a source broke
UA = "joshgreenman.com site builder (+https://joshgreenman.com)"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


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

def straighten(s):
    """Curly quotes and dashes out, per the house style of the page."""
    return (s.replace("’", "'").replace("‘", "'")
             .replace("“", '"').replace("”", '"')
             .replace("…", "...").replace(" ", " ")).strip()


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
    title = straighten(title)
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

    names = {n.lower() for n in cfg["names"]}
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

        core = tok.strip("(){}[]\"'.,;:!?")
        bare = re.sub(r"'s$", "", core)

        if core.upper() in acronyms:
            word = tok.replace(core, core.upper())
        elif bare.lower() in names:
            keep = next(n for n in cfg["names"] if n.lower() == bare.lower())
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
        start_of_sentence = bool(re.search(r"[.?!:]\"?$", tok))

    title = "".join(out)
    for i, phrase in enumerate(slots):
        title = title.replace("\x00%d\x00" % i, phrase)
    return title.strip()


def esc(s):
    return html.escape(s, quote=True)


def short_date(iso):
    y, m, d = int(iso[0:4]), int(iso[5:7]), int(iso[8:10])
    return MONTHS[m - 1] + " " + str(y), MONTHS[m - 1] + " " + str(d) + ", " + str(y)


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
        t = straighten(p.get("title") or "")
        if not t or any(r.search(t) for r in skip):
            continue
        items.append({
            "title": t,
            "dek": straighten(p.get("custom_excerpt") or ""),
            "url": p.get("url") or "",
            "date": (p.get("published_at") or "")[:10],
            "outlet": "Vital City",
        })

    for p in sub:
        if p.get("type") not in (None, "newsletter"):
            continue
        t = straighten(p.get("title") or "")
        if not t or any(r.search(t) for r in skip):
            continue
        items.append({
            "title": t,
            "dek": straighten(p.get("subtitle") or p.get("description") or ""),
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
    return deduped[:WRITING_ITEMS]


def render_writing(items):
    lead, rest = items[0], items[1:]
    month_year, full = short_date(lead["date"])
    out = ['<a class="lead" href="%s" target="_blank" rel="noopener">'
           % esc(lead["url"]),
           '  <span class="kicker">Latest</span>',
           '  <span class="lead-t">%s<span class="arw">↗</span></span>'
           % esc(lead["title"])]
    if lead["dek"]:
        out.append('  <span class="lead-dek">%s</span>' % esc(lead["dek"]))
    out.append('  <span class="lead-m"><b>%s</b> · %s</span>'
               % (esc(lead["outlet"]), esc(full)))
    out.append('</a>')

    out.append('<div class="toc">')
    for it in rest:
        month_year, _ = short_date(it["date"])
        out.append('  <a href="%s" target="_blank" rel="noopener">'
                   % esc(it["url"]))
        out.append('    <span class="t">%s<span class="arw">↗</span></span>'
                   % esc(it["title"]))
        out.append('    <span class="m"><b>%s</b> · %s</span>'
                   % (esc(it["outlet"]), esc(month_year)))
        out.append('  </a>')
    out.append('</div>')
    return "\n".join(out)


# --------------------------------------------------------------------------
# experiments
# --------------------------------------------------------------------------

def split_title(t):
    """'Orrery - the music of the spheres' -> 'Orrery'."""
    t = straighten(t)
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
    dek = undash(straighten(html.unescape(re.sub(r"\s+", " ", d.group(3)))))
    if not title or not (50 <= len(dek) <= 240) or not dek.endswith((".", "?")):
        return None
    return {"title": title, "dek": dek}


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
        url = p.get("livePagesUrl") or ""
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
        meta = page_meta(p["livePagesUrl"])
        if not meta:
            sys.stderr.write("  skipped %s (no usable title/description)\n"
                             % p.get("name"))
            continue
        picked.append({
            "url": p["livePagesUrl"],
            "date": (p.get("created") or "")[:10],
            "title": cfg["experiment_titles"].get(p["name"], meta["title"]),
            "dek": cfg["experiment_deks"].get(p["name"], meta["dek"]),
        })
        if len(picked) == NEW_EXPERIMENTS:
            break

    if len(picked) < NEW_EXPERIMENTS:
        die("found only %d publishable new experiments, expected %d"
            % (len(picked), NEW_EXPERIMENTS))
    return picked


def render_experiments(items):
    out = ['<div class="grid grid-new">']
    for it in items:
        _, full = short_date(it["date"])
        out.append('  <a class="card card-new" href="%s" target="_blank" rel="noopener">'
                   % esc(it["url"]))
        out.append('    <div class="ck"><span class="kicker">New</span>'
                   '<span class="no">%s</span></div>' % esc(full))
        out.append('    <h3>%s</h3>' % esc(it["title"]))
        out.append('    <p>%s</p>' % esc(it["dek"]))
        out.append('    <span class="go">Open<span class="x">↗</span></span>')
        out.append('  </a>')
    out.append('</div>')
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

    # Hand-picked experiment cards keep their spot; the new pair never repeats one.
    already = {u.rstrip("/") for u in
               re.findall(r'<a class="card" href="([^"]+)"', page)}

    writing = collect_writing(cfg)
    print("writing: %d pieces, newest %s (%s)"
          % (len(writing), writing[0]["title"], writing[0]["date"]))

    experiments = collect_experiments(cfg, already)
    print("experiments: " + ", ".join("%s (%s)" % (e["title"], e["date"])
                                      for e in experiments))

    page = replace_block(page, "WRITING", render_writing(writing))
    page = replace_block(page, "NEW-EXPERIMENTS", render_experiments(experiments))

    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(page)
    print("index.html written")


if __name__ == "__main__":
    main()
