#!/usr/bin/env python3
"""Harvest the full GITenberg Book table via the (still-live) EB app's list pages.

The EB app paginates the whole DB at /books?page=N (10 books/page). all_repos.txt
is broken (502) but the list view works, so we walk pages until empty.
Polite rate; resumable via a JSONL progress file.

Output: harvest/books_db.jsonl  (one JSON object per book: id, repo, title)
"""
import json, os, re, sys, time, html
import urllib.request, ssl

BASE = "https://giten-site2-dev2.us-east-1.elasticbeanstalk.com"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "harvest", "books_db.jsonl")
STATE = OUT + ".state"
DELAY = 0.22          # ~4.5 pages/sec
TIMEOUT = 30
MAX_EMPTY = 3         # stop after N consecutive empty pages
MAX_PAGES = 20000     # hard backstop

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE  # cert is for *.gitenberg.org; host is EB CNAME

# Matches the DEPLOYED template (differs from the repo's): h5.booktitle with
# /book/<id> link, p.bookauthor, then the GitHub repo button.
ENTRY_RE = re.compile(
    r'<h5 class="booktitle"[^>]*><a href="/book/(?P<gid>\d+)">(?P<title>.*?)</a></h5>\s*'
    r'<p class="bookauthor">(?P<author>.*?)</p>.*?'
    r'href="https://github\.com/GITenberg/(?P<repo>[^"]+)"',
    re.S)

def fetch(page, tries=4):
    url = f"{BASE}/books?page={page}"
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gitenberg-archive/1.0 (catalog snapshot)"})
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            wait = 2 ** t
            print(f"page {page} try {t+1}: {e}; sleep {wait}s", flush=True)
            time.sleep(wait)
    return None

def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()

def parse(page_html):
    books = []
    for m in ENTRY_RE.finditer(page_html):
        books.append({
            "gid": int(m.group("gid")),
            "repo": m.group("repo").strip(),
            "title": clean(m.group("title")),
            "author": clean(m.group("author")),
        })
    return books

def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    start = 1
    if os.path.exists(STATE):
        start = int(open(STATE).read().strip()) + 1
        print(f"resuming from page {start}", flush=True)
    out = open(OUT, "a", encoding="utf-8")
    empty = 0
    total = 0
    t0 = time.time()
    for page in range(start, MAX_PAGES):
        h = fetch(page)
        if h is None:
            print(f"page {page}: unrecoverable; stopping for resume", flush=True)
            break
        books = parse(h)
        if not books:
            empty += 1
            print(f"page {page}: EMPTY ({empty}/{MAX_EMPTY})", flush=True)
            if empty >= MAX_EMPTY:
                print("done: end of catalog", flush=True)
                break
        else:
            empty = 0
            for b in books:
                out.write(json.dumps(b, ensure_ascii=False) + "\n")
            total += len(books)
        out.flush()
        with open(STATE, "w") as f:
            f.write(str(page))
        if page % 200 == 0:
            rate = (page - start + 1) / max(time.time() - t0, 1)
            print(f"page {page}: +{total} books this run, {rate:.1f} pages/s", flush=True)
        time.sleep(DELAY)
    out.close()
    print(f"TOTAL harvested this run: {total}", flush=True)

if __name__ == "__main__":
    main()
