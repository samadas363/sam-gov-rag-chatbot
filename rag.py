"""Chunking, vector indexing (ChromaDB), retrieval, and Claude answer generation."""
import os
import re
from datetime import date

import anthropic
import chromadb

from naics import label, psc_label

DB_DIR = "chroma_db"
COLLECTION = "sam_opportunities"
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
CONDENSE_MODEL = os.getenv("CONDENSE_MODEL", "claude-haiku-5-5")
NO_DEADLINE = 99991231  # notices without a deadline are treated as open

SYSTEM_PROMPT = """You are a government contracting analyst assistant.
Today's date is {today}.
Answer the user's question using ONLY the numbered SAM.gov notices provided.
- Cite sources inline like [1], [2].
- Refer to them as "the indexed notices", never "the context".
- A notice whose response deadline is before today's date is closed; say so. Otherwise treat it as open.
- You only see the top matches for each question, not the whole database. For questions about totals, rankings, or which agency has the most, say the answer covers only the notices retrieved.
- If the notices don't contain the answer, say so plainly; do not guess.
- Notices marked (PREVIOUS RESULT) are what the user's earlier question was about. If the question says "those", "them" or similar, answer ONLY about those notices, and only the ones the previous answer presented as matching the user's earlier question. Ignore notices it mentioned only to exclude them.
- Citation numbers restart with every question; never comment on citation numbers in earlier answers.
- If the question is unrelated to the notices, say so in one or two sentences and do not summarize the notices.
- Be concise and practical. You are not giving legal advice."""


def _deadline_int(s: str) -> int:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s or "")
    return int("".join(m.groups())) if m else NO_DEADLINE


def _today_int() -> int:
    return int(date.today().strftime("%Y%m%d"))


def get_collection():
    client = chromadb.PersistentClient(path=DB_DIR)
    # Chroma's default embedding model (MiniLM, runs locally) is used automatically.
    return client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})


def chunk_text(text: str, size: int = 900, overlap: int = 150):
    text = text.strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


def _header(o: dict) -> str:
    return (
        f"Title: {o['title']}\nAgency: {o['agency']}\n"
        f"Solicitation #: {o['solicitation_number']}\nType: {o['type']}\n"
        f"NAICS: {label(o['naics'])}\nPSC: {psc_label(o.get('psc'))}\nSet-aside: {o['set_aside']}\n"
        f"Posted: {o['posted']}\nResponse deadline: {o['deadline'] or 'N/A'}"
    )


def index_opportunities(opps: list[dict]) -> int:
    col = get_collection()
    ids, docs, metas = [], [], []
    for o in opps:
        meta = {k: str(o.get(k, "") or "") for k in
                ("notice_id", "title", "agency", "naics", "psc", "set_aside", "posted", "deadline", "url")}
        meta["deadline_int"] = _deadline_int(o.get("deadline", ""))
        pieces = [_header(o)] + [f"{o['title']} (description): {c}"
                                 for c in chunk_text(o.get("description", ""))]
        for i, piece in enumerate(pieces):
            ids.append(f"{o['notice_id']}-{i}")
            docs.append(piece)
            metas.append(meta)
    if ids:
        col.upsert(ids=ids, documents=docs, metadatas=metas)
    return len(ids)


def backfill() -> int:
    """Add the numeric deadline field to notices indexed before it existed (no API calls)."""
    col = get_collection()
    if col.count() == 0:
        return 0
    res = col.get(include=["metadatas"])
    ids, metas = [], []
    for i, m in zip(res["ids"], res["metadatas"]):
        if "deadline_int" not in m:
            m = dict(m)
            m["deadline_int"] = _deadline_int(m.get("deadline", ""))
            ids.append(i)
            metas.append(m)
    if ids:
        col.update(ids=ids, metadatas=metas)
    return len(ids)


def count() -> int:
    return get_collection().count()


def list_notices(open_only: bool = False) -> list[dict]:
    """One row per notice, sorted by deadline (for the Browse table)."""
    col = get_collection()
    if col.count() == 0:
        return []
    seen = {}
    for m in col.get(include=["metadatas"])["metadatas"]:
        seen[m["notice_id"]] = m
    rows = [m for m in seen.values()
            if not open_only or m.get("deadline_int", NO_DEADLINE) >= _today_int()]
    return sorted(rows, key=lambda m: m.get("deadline_int", NO_DEADLINE))


def retrieve(query: str, k: int = 12, naics: str | None = None, open_only: bool = False):
    col = get_collection()
    if col.count() == 0:
        return []
    conds = []
    if naics:
        conds.append({"naics": naics})
    if open_only:
        conds.append({"deadline_int": {"$gte": _today_int()}})
    where = None if not conds else (conds[0] if len(conds) == 1 else {"$and": conds})
    res = col.query(query_texts=[query], n_results=min(k, col.count()), where=where)
    return [{"text": d, "meta": m, "distance": dist}
            for d, m, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])]


def _text(resp) -> str:
    """Join text blocks only (responses can also contain thinking blocks)."""
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def condense_query(query: str, history: list[dict]) -> str:
    """Turn a follow-up like 'Which of those is due first?' into a standalone search query."""
    if not history:
        return query
    convo = "\n".join(f"{m['role']}: {m['content'][:600]}" for m in history[-4:])
    prompt = (
        "Rewrite the user's latest question as a standalone search query. Resolve references like "
        "'those' or 'it' using the conversation, and keep the subject, agency, codes and other "
        "specifics from the earlier discussion. Output only the rewritten query.\n\n"
        f"Conversation:\n{convo}\n\nLatest question: {query}"
    )
    try:
        resp = anthropic.Anthropic().messages.create(
            model=CONDENSE_MODEL, max_tokens=150,
            messages=[{"role": "user", "content": prompt}])
        return _text(resp) or query
    except Exception:
        return query


FOLLOW = re.compile(r"\b(those|these|them|they|that one|which of)\b", re.I)


def pinned(ids):
    """Header chunk of each notice from the previous answer (used for follow-up questions)."""
    res = get_collection().get(ids=[f"{n}-0" for n in ids], include=["documents", "metadatas"])
    return [{"text": d, "meta": m, "distance": 0.0, "pinned": True}
            for d, m in zip(res["documents"], res["metadatas"])]


def answer(query: str, history: list[dict], k: int = 12, naics: str | None = None,
           open_only: bool = False, prev_ids: list[str] | None = None):
    search_query = condense_query(query, history)
    hits = retrieve(search_query, k, naics, open_only)
    if prev_ids and FOLLOW.search(query):
        pins = pinned(prev_ids)
        seen = {h["meta"]["notice_id"] for h in pins}
        hits = pins + [h for h in hits if h["meta"]["notice_id"] not in seen]
    if not hits:
        return "No matching notices. Try turning off the filters or loading more data from the sidebar.", []

    context = "\n\n".join(
        f"[{i}]{' (PREVIOUS RESULT)' if h.get('pinned') else ''} ({h['meta']['title']} | notice {h['meta']['notice_id']})\n{h['text']}"
        for i, h in enumerate(hits, 1)
    )
    past = [{"role": m["role"], "content": re.sub(r"\s*\[\d+\]", "", m["content"])}
            for m in history[-6:]]
    messages = past + [{
        "role": "user",
        "content": f"<context>\n{context}\n</context>\n\nQuestion: {query}",
    }]
    resp = anthropic.Anthropic().messages.create(
        model=MODEL, max_tokens=2048,
        system=SYSTEM_PROMPT.format(today=date.today().strftime("%B %d, %Y")),
        messages=messages)
    return _text(resp), hits
