#!/usr/bin/env python3
"""Deterministic completion of the catalog harvest.

The page-walk harvest is non-deterministic (unordered queryset + OFFSET), so this
probes /books/<id>.json for every candidate id NOT already harvested. 200 -> book
exists (capture title/author/language); 404 -> id not in DB. Resumable.

Output: harvest/books_probe.jsonl  ({gid, repo, title, author, language})
State:  harvest/probe.state       (last id fully processed)
"""
import json, os, re, ssl, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://giten-site2-dev2.us-east-1.elasticbeanstalk.com"
WALK = os.path.join(HERE, "harvest", "books_db.jsonl")
OUT = os.path.join(HERE, "harvest", "books_probe.jsonl")
STATE = os.path.join(HERE, "harvest", "probe.state")
MAX_ID = 76500
DELAY = 0.15
TIMEOUT = 25

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def known_gids():
    seen = set()
    if os.path.exists(WALK):
        for line in open(WALK, encoding="utf-8"):
            line = line.strip()
            if line:
                seen.add(json.loads(line)["gid"])
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            line = line.strip()
            if line:
                d = json.loads(line)
                seen.add(d["gid"])
    return seen

def fetch(gid, tries=3):
    url = f"{BASE}/books/{gid}.json"
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gitenberg-archive/1.0 (catalog snapshot)"})
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, None
            time.sleep(2 ** t)
        except Exception:
            time.sleep(2 ** t)
    return None, None

def main():
    seen = known_gids()
    start = 1
    if os.path.exists(STATE):
        start = int(open(STATE).read().strip()) + 1
        print(f"resuming from id {start}", flush=True)
    todo = [g for g in range(start, MAX_ID + 1) if g not in seen]
    print(f"known={len(seen)}  probing {len(todo)} candidate ids ({start}..{MAX_ID})", flush=True)
    out = open(OUT, "a", encoding="utf-8")
    found = missing = errors = 0
    t0 = time.time()
    for i, gid in enumerate(todo):
        status, body = fetch(gid)
        if status == 200 and body:
            try:
                d = json.loads(body)
                title = re.sub(r"\s+", " ", (d.get("title") or "")).strip()
                author = ((d.get("creator") or {}).get("author") or {}).get("agent_name", "")
                out.write(json.dumps({
                    "gid": gid,
                    "repo": (d.get("_repo") or "").strip(),
                    "title": title,
                    "author": (author or "").strip(),
                    "language": (d.get("language") or "").strip() or "und",
                }, ensure_ascii=False) + "\n")
                found += 1
            except Exception as e:
                print(f"id {gid}: parse error {e}", flush=True)
                errors += 1
        elif status == 404:
            missing += 1
        else:
            errors += 1
            print(f"id {gid}: status={status}", flush=True)
        with open(STATE, "w") as f:
            f.write(str(gid))
        if (i + 1) % 500 == 0:
            rate = (i + 1) / max(time.time() - t0, 1)
            out.flush()
            print(f"{i+1}/{len(todo)}  found={found} missing={missing} err={errors}  {rate:.1f}/s", flush=True)
        time.sleep(DELAY)
    out.close()
    print(f"DONE probing: found={found} missing={missing} errors={errors}", flush=True)

if __name__ == "__main__":
    main()
