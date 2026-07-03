# GITenberg static catalog

A **self-contained static** version of the GITenberg book catalog — home, a client-side
search over the full catalog (~43k public-domain books), and content pages. No server,
no database: every page is a plain file, and search runs entirely in the browser.

Each book links to its GitHub repository (`github.com/GITenberg/<repo>`) and its
Project Gutenberg page.

## Rebuild

```
python3 build.py
```

Reads the GITenberg metadata snapshot (`giten_site/assets/GITenberg_repos_list_2.tsv`)
and regenerates `docs/` — `books.json` plus the static HTML. Host `docs/` on any static
host (this repo serves it via GitHub Pages).

## Why

Replaces the retired Django `giten_site` app (Elastic Beanstalk, Amazon Linux 2) with
static files that need no maintenance. See `gitenberg-dev/giten_site#102`.
