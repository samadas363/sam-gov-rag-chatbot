"""Thin client for the SAM.gov Get Opportunities API (v2)."""
import html
import os
import re
import time
from datetime import datetime, timedelta

import requests

BASE_URL = "https://api.sam.gov/opportunities/v2/search"


def _clean_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _fetch_description(url: str, api_key: str) -> str:
    try:
        r = requests.get(url, params={"api_key": api_key}, timeout=30)
        r.raise_for_status()
        try:
            return _clean_html(r.json().get("description", ""))
        except ValueError:
            return _clean_html(r.text)
    except requests.RequestException:
        return ""


def _normalize(o: dict) -> dict:
    return {
        "notice_id": o.get("noticeId", ""),
        "title": o.get("title", ""),
        "solicitation_number": o.get("solicitationNumber", ""),
        "agency": o.get("fullParentPathName", ""),
        "type": o.get("type", ""),
        "naics": o.get("naicsCode", "") or "",
        "psc": o.get("classificationCode", "") or "",
        "set_aside": o.get("typeOfSetAsideDescription", "") or "None",
        "posted": o.get("postedDate", ""),
        "deadline": o.get("responseDeadLine", "") or "",
        "url": o.get("uiLink", ""),
        "description": "",
        "_desc_url": o.get("description", ""),
    }


def fetch_opportunities(days=14, limit=50, naics=None, keyword=None,
                        ptype="o", with_descriptions=True, psc=None):
    """ptype: o=solicitation, k=combined synopsis/solicitation, p=presolicitation, r=sources sought."""
    api_key = os.environ["SAM_API_KEY"]
    now = datetime.now()
    params = {
        "api_key": api_key,
        "postedFrom": (now - timedelta(days=days)).strftime("%m/%d/%Y"),
        "postedTo": now.strftime("%m/%d/%Y"),
        "limit": limit,
        "offset": 0,
        "ptype": ptype,
    }
    if naics:
        params["ncode"] = naics
    if psc:
        params["ccode"] = psc
    if keyword:
        params["title"] = keyword

    r = requests.get(BASE_URL, params=params, timeout=60)
    if not r.ok:
        raise RuntimeError(f"SAM.gov returned HTTP {r.status_code}: {r.text[:300]}")
    opps = [_normalize(o) for o in r.json().get("opportunitiesData", [])]

    if with_descriptions:
        for o in opps:
            if o["_desc_url"]:
                o["description"] = _fetch_description(o["_desc_url"], api_key)
                time.sleep(0.3)
    for o in opps:
        o.pop("_desc_url", None)
    return opps
