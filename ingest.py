"""CLI:
  python ingest.py --naics 541370 --days 90 --limit 25 --no-desc
  python ingest.py --psc T002 --days 90 --limit 25 --no-desc
  python ingest.py --targets --days 90 --limit 25 --no-desc     (all NAICS + PSC in naics.py)
Notice types (--ptypes): o=solicitation, k=combined synopsis/solicitation,
p=presolicitation, r=sources sought, s=special notice
"""
import argparse
import json

from dotenv import load_dotenv

import naics
import rag
import sam_client

load_dotenv()


def load_sample():
    with open("sample_data/sample_opportunities.json") as f:
        return json.load(f)


def pull(kind, code, a, desc):
    found = []
    for pt in [x.strip() for x in a.ptypes.split(",") if x.strip()]:
        got = sam_client.fetch_opportunities(
            a.days, a.limit,
            naics=code if kind == "NAICS" else None,
            keyword=a.keyword, ptype=pt, with_descriptions=desc,
            psc=code if kind == "PSC" else None)
        print(f"  {kind} {code or '(keyword only)'} [type {pt}]: {len(got)} notices")
        found += got
    return found


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--sample", action="store_true", help="use bundled synthetic data")
    p.add_argument("--targets", action="store_true", help="fetch every code in naics.py")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--limit", type=int, default=50, help="max notices per code and type")
    p.add_argument("--naics")
    p.add_argument("--psc")
    p.add_argument("--keyword")
    p.add_argument("--ptypes", default="o,k", help="comma-separated notice types")
    p.add_argument("--no-desc", action="store_true", help="skip per-notice description fetches")
    a = p.parse_args()
    desc = not a.no_desc

    opps = []
    if a.sample:
        opps = load_sample()
    elif a.targets:
        for code in naics.TARGET_NAICS:
            if len(code) != 6 or not code.isdigit():
                print(f"Skipping NAICS {code}: must be 6 digits")
                continue
            opps += pull("NAICS", code, a, desc)
        for code in naics.TARGET_PSC:
            if len(code) != 4 or not code.isalnum():
                print(f"Skipping PSC {code}: must be 4 characters")
                continue
            opps += pull("PSC", code, a, desc)
    else:
        if a.naics:
            opps += pull("NAICS", a.naics, a, desc)
        if a.psc:
            opps += pull("PSC", a.psc, a, desc)
        if not a.naics and not a.psc:
            opps += pull("NAICS", None, a, desc)

    unique = {o["notice_id"]: o for o in opps}
    opps = list(unique.values())
    print(f"Fetched {len(opps)} unique opportunities")
    print(f"Indexed {rag.index_opportunities(opps)} chunks (total in DB: {rag.count()})")
