#!/usr/bin/env python3
"""
build.py — generate a self-contained static GITenberg book catalog.

Reads the GITenberg repo list (TSV) and emits a static site:
  site/index.html            home + mission + stats
  site/books.html            client-side search over the whole catalog
  site/faq.html, get-involved.html, license.html
  site/data/books.json       compact catalog data (array of [id,repo,title,lang,downloads])
  site/assets/style.css      shared styles

Data source of truth is the GITenberg GitHub metadata; this TSV is a snapshot of it.
Re-run this script to regenerate from a fresh snapshot. No server/DB required.
"""
import csv, json, os, html, re, sys, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
TSV = os.path.expanduser("~/C/src/gitenberg-dev/giten_site/assets/GITenberg_repos_list_2.tsv")
SRC_ASSETS = os.path.expanduser("~/C/src/gitenberg-dev/giten_site/assets")
SITE = os.path.join(HERE, "docs")   # /docs so GitHub Pages can serve it from the default branch
DATA = os.path.join(SITE, "data")

csv.field_size_limit(10_000_000)

HARVEST_WALK = os.path.join(HERE, "harvest", "books_db.jsonl")     # page-walk (title, author)
HARVEST_PROBE = os.path.join(HERE, "harvest", "books_probe.jsonl")  # /books/<id>.json (title, author, language)

def load_tsv_enrichment():
    """language + downloads from the old repo TSV snapshot (subset of books)."""
    enrich = {}
    if not os.path.exists(TSV):
        return enrich
    with open(TSV, newline="", encoding="utf-8", errors="replace") as f:
        r = csv.reader(f, delimiter="\t")
        next(r, None)
        for row in r:
            if len(row) < 6 or not row[1].strip().isdigit():
                continue
            gid = int(row[1])
            lang = (row[4] or "").strip() or "und"
            dl = int(row[5]) if row[5].strip().isdigit() else 0
            if gid not in enrich or dl > enrich[gid][1]:
                enrich[gid] = (lang, dl)
    return enrich

def _read_jsonl(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

HARVEST_CSV = os.path.join(HERE, "harvest", "books_db.csv")  # authoritative direct DB dump

def _authors_from_http():
    """gid -> author, gleaned from the HTTP harvests (the DB Book table has no
    author column; author lives in the per-book metadata the JSON endpoint exposes)."""
    a = {}
    for d in list(_read_jsonl(HARVEST_WALK)) + list(_read_jsonl(HARVEST_PROBE)):
        au = re.sub(r"\s+", " ", (d.get("author") or "").strip())
        if au:
            a[int(d["gid"])] = au
    return a

def load_books():
    """Book catalog snapshot (2026-07-03) from the retiring EB app's database.

    Preferred source: harvest/books_db.csv — a direct `SELECT ... FROM bookinfo_book`
    dump (authoritative, complete, exact). Author is backfilled from the HTTP harvest
    where available (no author column in the DB table). If the CSV is absent, fall
    back to the two HTTP harvests merged/deduped by Gutenberg id.

    Download counts are omitted deliberately: the DB never stored them; the 2015 TSV
    'downloads' column was a one-off snapshot, a decade stale."""
    tsv = load_tsv_enrichment()  # gid -> (lang, downloads); a 2015 snapshot, ~43k books
    tsv_lang = {g: l for g, (l, _d) in tsv.items()}
    tsv_dl = {g: d for g, (_l, d) in tsv.items()}
    seen = {}
    # record: [gid, repo, title, lang, author, downloads]  (downloads 0 = unknown)
    if os.path.exists(HARVEST_CSV):
        authors = _authors_from_http()
        with open(HARVEST_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gid = int(row["book_id"])
                title = re.sub(r"\s+", " ", (row.get("title") or "").strip())
                if not title:
                    continue
                lang = (row.get("language") or "").strip() or tsv_lang.get(gid) or "und"
                seen[gid] = [gid, (row.get("repo_name") or "").strip(), title, lang,
                             authors.get(gid, ""), tsv_dl.get(gid, 0)]
    else:
        # HTTP fallback: page-walk first, probe second so probe (has language) wins
        for d in list(_read_jsonl(HARVEST_WALK)) + list(_read_jsonl(HARVEST_PROBE)):
            gid = int(d["gid"])
            title = re.sub(r"\s+", " ", (d.get("title") or "").strip())
            if not title:
                continue
            author = re.sub(r"\s+", " ", (d.get("author") or "").strip())
            lang = (d.get("language") or "").strip() or tsv_lang.get(gid) or "und"
            seen[gid] = [gid, (d.get("repo") or "").strip(), title, lang, author, tsv_dl.get(gid, 0)]
    books = sorted(seen.values(), key=lambda b: b[2].lower())
    return books

def stats(books):
    langs = {}
    authors = set()
    with_dl = 0
    for _, _, _, lang, author, dl in books:
        if lang != "und":
            langs[lang] = langs.get(lang, 0) + 1
        if author:
            authors.add(author)
        if dl:
            with_dl += 1
    top_langs = sorted(langs.items(), key=lambda kv: -kv[1])
    return {"count": len(books), "languages": len(langs),
            "authors": len(authors), "with_dl": with_dl, "top_langs": top_langs}

# ---------- shared chrome ----------
def page(title, active, body, extra_head=""):
    nav = [("index.html", "Home"), ("books.html", "Books"),
           ("faq.html", "FAQ"), ("get-involved.html", "Get Involved"),
           ("license.html", "License")]
    links = "".join(
        '<a class="{cls}" href="{href}">{label}</a>'.format(
            cls="on" if href == active else "", href=href, label=label)
        for href, label in nav)
    return TPL.replace("%%TITLE%%", html.escape(title)) \
             .replace("%%NAV%%", links) \
             .replace("%%EXTRA_HEAD%%", extra_head) \
             .replace("%%BODY%%", body)

TPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<link rel="icon" href="assets/favicon.ico">
<link rel="stylesheet" href="assets/style.css">
%%EXTRA_HEAD%%
</head>
<body>
<header class="site">
  <a class="brand" href="index.html"><img src="assets/Gitenberg_full.svg" alt="GITenberg"></a>
  <nav>%%NAV%%</nav>
</header>
<main>%%BODY%%</main>
<footer class="site">
  <p>A static archive of the GITenberg catalog &middot; July 2026 snapshot of the
     GITenberg catalog database &middot; books are in the public domain,
     <a href="license.html">free for any use</a>.</p>
</footer>
</body>
</html>
"""

CSS = """
:root{
  --green:#2bac3a; --green-d:#1f8f2e; --red:#e8352b; --ink:#2a2c2b;
  --muted:#6b6f6d; --line:#e7e4dc; --bg:#faf9f6; --card:#ffffff;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
a{color:var(--green-d);text-decoration:none}
a:hover{text-decoration:underline}
h1,h2,h3{font-family:Georgia,"Times New Roman",serif;line-height:1.2;color:var(--ink)}
header.site{display:flex;align-items:center;justify-content:space-between;gap:1rem;
  padding:.7rem 1.25rem;background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
header.site .brand img{height:34px;display:block}
header.site nav{display:flex;flex-wrap:wrap;gap:.25rem}
header.site nav a{padding:.4rem .7rem;border-radius:6px;color:var(--muted);font-weight:600;font-size:.93rem}
header.site nav a:hover{background:#f1efe9;text-decoration:none;color:var(--ink)}
header.site nav a.on{color:var(--green-d);background:#eaf6ec}
main{max-width:1000px;margin:0 auto;padding:1.5rem 1.25rem 3rem}
footer.site{border-top:1px solid var(--line);color:var(--muted);font-size:.85rem;
  text-align:center;padding:1.5rem 1.25rem;max-width:1000px;margin:0 auto}
/* home */
.hero{text-align:center;padding:2rem 0 1rem}
.hero h1{font-size:2.4rem;margin:.2rem 0 .6rem}
.hero p.lead{font-size:1.15rem;color:var(--muted);max-width:640px;margin:0 auto 1.4rem}
.btn{display:inline-block;background:var(--green);color:#fff;font-weight:700;
  padding:.7rem 1.3rem;border-radius:8px;font-size:1.02rem}
.btn:hover{background:var(--green-d);text-decoration:none}
.stats{display:flex;gap:1rem;justify-content:center;flex-wrap:wrap;margin:2rem 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:1.1rem 1.6rem;min-width:150px}
.stat .n{font-family:Georgia,serif;font-size:1.9rem;font-weight:700;color:var(--green-d)}
.stat .l{color:var(--muted);font-size:.85rem;text-transform:uppercase;letter-spacing:.04em}
.prose{max-width:720px;margin:0 auto}
.prose h2{margin-top:2rem;border-bottom:1px solid var(--line);padding-bottom:.3rem}
.prose h3{margin-top:1.4rem}
.prose li{margin:.3rem 0}
/* books */
.searchbar{position:sticky;top:60px;background:var(--bg);padding:.6rem 0 .8rem;z-index:4}
.searchrow{display:flex;gap:.6rem;flex-wrap:wrap}
#q{flex:1;min-width:220px;font-size:1.1rem;padding:.75rem 1rem;border:2px solid var(--line);
  border-radius:10px;background:#fff}
#q:focus{outline:none;border-color:var(--green)}
#lang{font-size:1rem;padding:.75rem;border:2px solid var(--line);border-radius:10px;background:#fff}
.count{color:var(--muted);font-size:.9rem;margin:.2rem 0 .6rem}
ol.results{list-style:none;padding:0;margin:0}
ol.results li{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:.75rem 1rem;margin-bottom:.55rem;display:flex;gap:1rem;align-items:baseline}
.rank{color:var(--muted);font-variant-numeric:tabular-nums;min-width:2.2em;text-align:right;font-size:.9rem}
.bk{flex:1;min-width:0}
.bk .t{font-family:Georgia,serif;font-size:1.12rem;font-weight:600}
.bk .m{color:var(--muted);font-size:.86rem;margin-top:.2rem;display:flex;gap:.9rem;flex-wrap:wrap;align-items:center}
.badge{background:#eef3ef;color:#4a6b50;border-radius:20px;padding:.05rem .55rem;font-size:.78rem;font-weight:600}
.dl{font-variant-numeric:tabular-nums}
.loading{color:var(--muted);padding:2rem 0;text-align:center}
@media(max-width:560px){header.site .brand img{height:28px}.hero h1{font-size:1.9rem}}
"""

def home(st):
    def fmt(n): return "{:,}".format(n)
    body = """
<section class="hero">
  <h1>The GITenberg Catalog</h1>
  <p class="lead">A collaborative, open-source community curating public-domain ebooks on GitHub &mdash;
     with detailed metadata, in many formats, <a href="license.html">free for anyone to use for any purpose</a>.</p>
  <a class="btn" href="books.html">Browse the catalog &rarr;</a>
  <div class="stats">
    <div class="stat"><div class="n">%%BOOKS%%</div><div class="l">Books</div></div>
    <div class="stat"><div class="n">%%AUTHORS%%</div><div class="l">Authors</div></div>
    <div class="stat"><div class="n">%%LANGS%%</div><div class="l">Languages</div></div>
  </div>
</section>
<section class="prose">
  <h2>What is this?</h2>
  <p>GITenberg puts public-domain books on GitHub, where each book is a repository of text and
     metadata that anyone can read, fork, correct, and improve &mdash; the same tools that power
     open-source software, applied to our shared cultural heritage.</p>
  <p>This is a <strong>static archive</strong> of the catalog: every page here is a plain file,
     with search running entirely in your browser. No server, no database &mdash; it can be hosted
     on any static host and regenerated any time from the GITenberg metadata.</p>
</section>
""".replace("%%BOOKS%%", fmt(st["count"])) \
   .replace("%%AUTHORS%%", fmt(st["authors"])) \
   .replace("%%LANGS%%", fmt(st["languages"]))
    return page("GITenberg — public-domain ebooks on GitHub", "index.html", body)

def books_page(st):
    top = [l for l, _ in st["top_langs"][:12] if l != "und"]
    opts = '<option value="">All languages</option>' + \
        "".join('<option value="{0}">{0}</option>'.format(l) for l in top)
    body = """
<h1 style="text-align:center">Browse %%BOOKS%% books</h1>
<div class="searchbar">
  <div class="searchrow">
    <input id="q" type="search" placeholder="Search by title, author keyword, or Gutenberg id…" autocomplete="off" autofocus>
    <select id="sort">
      <option value="title">Sort: Title (A–Z)</option>
      <option value="downloads">Sort: Most downloaded</option>
    </select>
    <select id="lang">%%OPTS%%</select>
  </div>
</div>
<div class="count" id="count">Loading the catalog…</div>
<ol class="results" id="results"></ol>
<div class="loading" id="more"></div>
""".replace("%%BOOKS%%", "{:,}".format(st["count"])).replace("%%OPTS%%", opts)
    js = """
<script>
const LIMIT = 100;
let BOOKS = [], view = [];
const $q = document.getElementById('q'), $lang = document.getElementById('lang'),
      $sort = document.getElementById('sort'),
      $res = document.getElementById('results'), $count = document.getElementById('count'),
      $more = document.getElementById('more');
function fmt(n){return n.toLocaleString();}
function esc(s){return s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function render(){
  const byDl = $sort.value==='downloads';
  const rows = view.slice(0, LIMIT).map((b,i)=>{
    const [id,repo,title,lang,author,dl] = b;
    const gh = 'https://github.com/GITenberg/'+encodeURIComponent(repo);
    const pg = 'https://www.gutenberg.org/ebooks/'+id;
    return '<li><span class="rank">'+(i+1)+'</span><div class="bk">'+
      '<div class="t"><a href="'+gh+'">'+esc(title)+'</a></div>'+
      '<div class="m">'+(author?'<span>'+esc(author)+'</span>':'')+
      (lang && lang!=='und' ? '<span class="badge">'+esc(lang)+'</span>' : '')+
      (dl ? '<span class="dl" title="Project Gutenberg downloads, 2015 snapshot">'+fmt(dl)+' downloads (2015)</span>' : '')+
      '<a href="'+gh+'">GitHub repo</a><a href="'+pg+'">Project Gutenberg</a>'+
      '<span style="color:#b3b6b3">#'+id+'</span></div></div></li>';
  }).join('');
  $res.innerHTML = rows;
  let note = view.length>LIMIT ? ' — showing the first '+LIMIT : '';
  $count.textContent = fmt(view.length) + ' book' + (view.length===1?'':'s') + note;
  $more.innerHTML = byDl
    ? 'Ranked by Project Gutenberg download counts from a 2015 snapshot (available for ~'+fmt(DL_COUNT)+' books; the rest sort after, alphabetically).'
    : (view.length>LIMIT ? 'Refine your search to see more.' : '');
}
function sortView(){
  if($sort.value==='downloads')
    view.sort((a,b)=> (b[5]-a[5]) || a[2].toLowerCase().localeCompare(b[2].toLowerCase()));
  else
    view.sort((a,b)=> a[2].toLowerCase().localeCompare(b[2].toLowerCase()));
}
function apply(){
  const q = $q.value.trim().toLowerCase(), lang = $lang.value;
  const numeric = /^\\d+$/.test(q);
  view = BOOKS.filter(b=>{
    if(lang && b[3]!==lang) return false;
    if(!q) return true;
    if(numeric && String(b[0])===q) return true;
    return b[2].toLowerCase().includes(q) || (b[4] && b[4].toLowerCase().includes(q));
  });
  sortView();
  render();
}
let DL_COUNT = 0;
let t; function debounced(){clearTimeout(t);t=setTimeout(apply,110);}
$q.addEventListener('input',debounced); $lang.addEventListener('change',apply);
$sort.addEventListener('change',apply);
fetch('data/books.json').then(r=>r.json()).then(d=>{
  BOOKS=d; DL_COUNT=d.filter(b=>b[5]>0).length; view=d.slice(); sortView(); render();
}).catch(e=>{$count.textContent='Failed to load catalog: '+e;});
</script>
"""
    return page("Browse the GITenberg catalog", "books.html", body, extra_head="") \
        .replace("</main>", js + "\n</main>")

FAQ_BODY = """
<div class="prose">
<h1>Frequently Asked Questions</h1>
<h3>Why put books on GitHub?</h3>
<p>In modern software development, GitHub is a kind of Library of Alexandria &mdash; a massive
collection of text under open licenses that anyone can copy and change. On a computer, books and
source code look much the same: files of text. The tools that let people collaborate on open-source
software can be applied to books too. Each book is a repository &mdash; text files plus metadata and
history &mdash; that anyone can <em>fork</em> and improve. And GitHub is free for public open-source projects.</p>
<h3>Who is this for?</h3>
<p>Early GITenberg is mainly for developers and people comfortable with git and GitHub &mdash; but the
books we curate and publish are for the benefit of all.</p>
<h3>What can I do with these books?</h3>
<p>Anything you want. These books are in the public domain: quote them, edit them, print them, sell
them, or give them away, in whole or in part. See the <a href="license.html">license page</a> for details
(note that not all covers are cleared for commercial use).</p>
<h3>How do I find books?</h3>
<p>Use the <a href="books.html">catalog search</a> on this site, or search the
<a href="https://github.com/GITenberg">GITenberg organization</a> on GitHub directly.</p>
<h3>I found a problem in a book — who do I tell?</h3>
<p>Find the book on GitHub, open its <em>Issues</em> tab, and click <em>New Issue</em>. Paste the sentence
with the error exactly as written and describe what it should say. That's enough for anyone to fix it.</p>
<h3>Can I fix issues in books myself?</h3>
<p>Yes, please! This is a collaboration among people all over the world. Fork the book, make your edit,
and open a pull request.</p>
</div>
"""

GETINVOLVED_BODY = """
<div class="prose">
<h1>Get Involved</h1>
<p>Interested in contributing? Awesome. Everything below needs a (free) GitHub account.</p>
<p>If you find an error or typo in any book, report it in the <em>Issues</em> tab on that book's repo.
To offer changes: fork, edit, and open a pull request.</p>
<h3>Developers</h3>
<ul>
<li>Fork this site and submit pull requests</li>
<li>Convert Project Gutenberg HTML to EPUB</li>
<li>Help develop and implement a metadata specification for books</li>
<li>Write or update documentation</li>
</ul>
<h3>Editors</h3>
<ul>
<li>Help shape the metadata specification</li>
<li>Learn the AsciiDoc syntax</li>
<li>Choose a book you'd like to edit &mdash; and edit it</li>
</ul>
<h3>Everyone else</h3>
<ul>
<li>Request features and send feedback</li>
<li>Tell a friend &mdash; anything you can think of</li>
</ul>
<p>The <a href="https://github.com/GITenberg">GITenberg organization</a> on GitHub is the place to start.</p>
</div>
"""

LICENSE_BODY = """
<div class="prose">
<h1>License</h1>
<p>The books in the GITenberg catalog are in the <strong>public domain</strong>. You may quote, edit,
print, sell, or give them away, in whole or in part, for any purpose.</p>
<p>Book <em>text</em> comes from Project Gutenberg and the public domain. Some <em>cover images</em> and
certain added materials may carry their own terms &mdash; check the individual book repository if you plan
commercial use of a cover.</p>
<p>Each book's repository on <a href="https://github.com/GITenberg">GitHub</a> records its specific
metadata and any applicable notices.</p>
</div>
"""

def main():
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(os.path.join(SITE, "assets"), exist_ok=True)
    # branding assets (fully reproducible: no manual copy step needed)
    for a in ("Gitenberg_full.svg", "favicon.ico"):
        src = os.path.join(SRC_ASSETS, a)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(SITE, "assets", a))
    books = load_books()
    st = stats(books)
    with open(os.path.join(DATA, "books.json"), "w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(SITE, "assets", "style.css"), "w", encoding="utf-8") as f:
        f.write(CSS)
    pages = {
        "index.html": home(st),
        "books.html": books_page(st),
        "faq.html": page("GITenberg — FAQ", "faq.html", FAQ_BODY),
        "get-involved.html": page("GITenberg — Get Involved", "get-involved.html", GETINVOLVED_BODY),
        "license.html": page("GITenberg — License", "license.html", LICENSE_BODY),
    }
    for name, content in pages.items():
        with open(os.path.join(SITE, name), "w", encoding="utf-8") as f:
            f.write(content)
    size = os.path.getsize(os.path.join(DATA, "books.json"))
    print("Books:      {:,}".format(st["count"]))
    print("Authors:    {:,}".format(st["authors"]))
    print("Languages:  {:,}".format(st["languages"]))
    print("books.json: {:.1f} MB".format(size / 1e6))
    print("Top langs:  " + ", ".join("{}={}".format(l, n) for l, n in st["top_langs"][:6]))
    print("Output ->   " + SITE)

if __name__ == "__main__":
    main()
