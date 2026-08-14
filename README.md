# joshgreenman.com

Personal site: bio, selected writing, data experiments, contact.

Single self-contained `index.html`, no dependencies.
Served by GitHub Pages at https://joshgreenman.com

Contact form relays via Web3Forms (honeypot + time trap; the email
address is deliberately kept out of the page source).

## What updates itself

A GitHub Action (`.github/workflows/refresh.yml`) runs `build.py` every
morning and commits only if the page actually changed. It rewrites two
blocks in `index.html` and nothing else:

| Block | What it holds | Source |
| --- | --- | --- |
| `AUTO:WRITING` | Latest piece, played as a lead, then eight more | Substack archive API + Vital City Ghost API |
| `AUTO:NEW-EXPERIMENTS` | The two newest live experiments | `projects-manifest.json` in the experiments repo, then each project's own `<title>` and `<meta name="description">` |

Everything outside those markers is hand-written and is never touched:
the bio, the outlet chips, the twelve selected experiments, Elsewhere,
the contact form.

A piece that ran in Vital City and was mirrored on Substack counts once,
and links to Vital City. Editor's notes are left out. Titles are pulled
down into the page's sentence case, protecting proper nouns.

`build.py` **fails loudly**: if a source returns nothing, or returns less
than is plausible, it exits non-zero and writes nothing, so a broken feed
fails the Action instead of publishing an empty page.

## Steering it by hand

Edit `data/overrides.json`, never the generated HTML:

- `title_overrides` / `dek_overrides` — pin a headline or dek the
  automatic pass gets wrong
- `phrases`, `names`, `acronyms` — proper nouns the sentence-caser must
  leave alone
- `skip_titles` — regexes for pieces to keep off the list
- `experiment_deny` — projects that should never appear as New
- `experiment_titles` / `experiment_deks` — pin an experiment's card copy

Then run it locally to see the result before it goes out:

```
python3 build.py
```
