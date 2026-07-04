#!/usr/bin/env python3
"""Definitively resolve the remaining candidate ids (harvest/retry_ids.txt).

Per id, GET /books/<id>.json:
  200 -> real book; capture title/author/language from JSON
  404 -> id absent from DB; skip
  500/other -> real book whose JSON metadata is broken; fall back to the HTML
               /book/<id> page and derive repo+title from the GITenberg link.
Appends to harvest/books_probe.jsonl (build.py reads it). Resumable via finish.state.
"""
import json, os, re, ssl, time, urllib.request, urllib.error, html

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://giten-site2-dev2.us-east-1.elasticbeanstalk.com"
IDS = os.path.join(HERE, "harvest", "retry_ids.txt")
OUT = os.path.join(HERE, "harvest", "books_probe.jsonl")
STATE = os.path.join(HERE, "harvest", "finish.state")
DELAY = 0.15
TIMEOUT = 25

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def get(url, tries=3):
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gitenberg-archive/1.0 (catalog snapshot)"})
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, None          # 404/500 are answers, don't retry-storm
        except Exception:
            time.sleep(1.5 * (t + 1))
    return None, None

def title_from_repo(repo):
    # "Voyages-to-the-Moon-and-the-Sun_74000" -> "Voyages to the Moon and the Sun"
    base = re.sub(r"_\d+$", "", repo)
    base = base.replace("-amp-", " & ").replace("--", " ").replace("-", " ")
    return re.sub(r"\s+", " ", base).strip()

def resolve_html(gid):
    status, body = get(f"{BASE}/book/{gid}")
    if status != 200 or not body:
        return None
    t = body.decode("utf-8", "replace")
    m = re.search(r'https://github\.com/GITenberg/([^"/]+)', t)
    if not m:
        return None
    repo = m.group(1)
    return {"gid": gid, "repo": repo, "title": title_from_repo(repo),
            "author": "", "language": "und", "_source": "html_fallback"}

def main():
    ids = [int(x) for x in open(IDS).read().split() if x.strip().isdigit()]
    start_idx = 0
    if os.path.exists(STATE):
        last = int(open(STATE).read().strip())
        start_idx = next((i for i, g in enumerate(ids) if g > last), len(ids))
        print(f"resuming after id {last} (index {start_idx})", flush=True)
    out = open(OUT, "a", encoding="utf-8")
    found_json = found_html = absent = err = 0
    t0 = time.time()
    for i in range(start_idx, len(ids)):
        gid = ids[i]
        status, body = get(f"{BASE}/books/{gid}.json")
        rec = None
        if status == 200 and body:
            try:
                d = json.loads(body)
                a = ((d.get("creator") or {}).get("author") or {}).get("agent_name", "")
                rec = {"gid": gid, "repo": (d.get("_repo") or "").strip(),
                       "title": re.sub(r"\s+", " ", (d.get("title") or "")).strip(),
                       "author": (a or "").strip(),
                       "language": (d.get("language") or "").strip() or "und"}
                found_json += 1
            except Exception:
                rec = resolve_html(gid)
                if rec: found_html += 1
                else: err += 1
        elif status == 404:
            absent += 1
        else:  # 500 or transient: try HTML
            rec = resolve_html(gid)
            if rec: found_html += 1
            else: err += 1
        if rec and rec.get("title"):
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        with open(STATE, "w") as f:
            f.write(str(gid))
        if (i + 1) % 250 == 0:
            out.flush()
            rate = (i + 1 - start_idx) / max(time.time() - t0, 1)
            print(f"{i+1}/{len(ids)}  json={found_json} html={found_html} absent={absent} err={err}  {rate:.1f}/s", flush=True)
        time.sleep(DELAY)
    out.close()
    print(f"DONE finish: json={found_json} html={found_html} absent={absent} err={err}", flush=True)

if __name__ == "__main__":
    main()
