# joshgreenman.com

Personal site: a short bio beside everything Josh has published that still has
a working link, plus his data tools about New York City, newest first.

Single `index.html`, no build step to view it, no dependencies.
Served by GitHub Pages at https://joshgreenman.com

## What the page does

- **The list.** Every piece and tool, grouped by year, written into the HTML
  itself, so it loads fast, works without JavaScript and is readable by search
  engines. Everything below runs on top of it.
- **Search** across titles and summaries (press `/` to jump to the box). When a
  piece matches on its summary rather than its headline, the summary shows.
  The address bar carries the search, so `joshgreenman.com/?q=congestion`
  can be sent to someone. `?from=dn|vc|ss|other|tool` and `?year=2010` work too.
- **Filters** by outlet, and a **chart of pieces per year** that filters the
  list when a year is tapped.
- **On this date**: a piece published on today's date in an earlier year
  (or that week, if none), with a button for a random older one.
- **New since your last visit**: each reader's browser remembers the date of
  their last visit and marks anything newer. Nothing leaves their browser.
- **Hover a tool** (mouse or trackpad) to see a screenshot of it.
- **A live line** with New York City's electricity use, read from Grid Pulse's
  own data file. It says nothing if that file is stale or unreachable.
- **A short bio** for introductions, with a copy button.
- **Contact form** relayed via Web3Forms (honeypot + time trap; the email
  address is deliberately kept out of the page source).
- Follows the reader's light or dark setting.

## What updates itself

A GitHub Action (`.github/workflows/refresh.yml`) runs `build.py` every
morning and commits only if the page actually changed. It rewrites one block
in `index.html`, `AUTO:ARCHIVE`, and nothing else. Its sources:

| Source | What it adds |
| --- | --- |
| `data/archive-static.json` | Daily News, New York Sun, Washington Post and Politico pieces. Fixed; built once from the `archive/*.html` pages. |
| Substack archive API + Vital City Ghost API | Everything since, refreshed daily |
| `data/tools.json` | Hand-picked tools that always appear |
| `projects-manifest.json` in the experiments repo | The four newest tools, read from each one's own `<title>` and `<meta name="description">` |
| `shots/<last part of the URL>.jpg` | Screenshots for the hover previews |

Substack blocks GitHub's runners, so the same script also runs from the Mac
every morning (`refresh-local.sh`, via launchd). That run uses
`python3 build.py --shots`, which screenshots any newly listed tool with
Chrome; the cloud job can't, so a new tool gets its preview within a day.

A piece that ran in Vital City and was mirrored on Substack counts once and
links to Vital City. Editor's notes are left out. Titles are pulled down into
sentence case, protecting proper nouns.

`build.py` **fails loudly**: if a source returns nothing, or less than is
plausible, it exits non-zero and writes nothing, so a broken feed fails the
Action instead of publishing an empty page.

## Steering it by hand

Edit the data files, never the generated HTML:

- `data/overrides.json`
  - `title_overrides` / `dek_overrides`: pin a headline or summary the
    automatic pass gets wrong (keyed on the source's original title)
  - `phrases`, `names`, `acronyms`: proper nouns the sentence-caser must
    leave alone
  - `skip_titles`: regexes for pieces to keep off the list
  - `experiment_deny`: projects that should never be picked up as new tools
  - `experiment_titles` / `experiment_deks`: pin a tool's title or line
- `data/tools.json`: add a tool here to keep it on the list for good.

Then run it locally to see the result before it goes out:

```
python3 build.py
```
