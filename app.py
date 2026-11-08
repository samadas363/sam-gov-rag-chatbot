import os
import re

import streamlit as st
from dotenv import load_dotenv

import rag
import sam_client
from ingest import load_sample
from naics import NAICS_TITLES, label

load_dotenv()
st.set_page_config(page_title="Geospatial Solutions LLC | SAM.gov Contract Analyst", layout="wide")
st.title("SAM.gov Contract Analysis Chatbot")
st.caption("RAG over federal contract opportunities | ChromaDB + Claude")
st.markdown("**Built by Abdul Samad** | **Geospatial Solutions LLC** | [LinkedIn](https://www.linkedin.com/in/abdul-samad-da)")
st.caption("U.S. Federal Contracts Analyst | GovCon BD Intelligence | Solicitation Analysis | Compliance & Requirements Review | Bid/No-Bid Analysis | Python | SQL | AI & RAG Automation")

if "backfilled" not in st.session_state:
    rag.backfill()
    st.session_state.backfilled = True

with st.sidebar:
    st.markdown("**Geospatial Solutions LLC**  \nAbdul Samad")
    st.header("Data")
    st.metric("Indexed chunks", rag.count())

    if st.button("Load sample data (no API key)"):
        n = rag.index_opportunities(load_sample())
        st.success(f"Indexed {n} chunks")
        st.rerun()

    st.subheader("Fetch live from SAM.gov")
    days = st.slider("Posted in last N days", 1, 360, 30)
    limit = st.slider("Max notices", 5, 100, 25)
    f_naics = st.selectbox("NAICS code", ["All"] + list(NAICS_TITLES),
                           format_func=lambda c: c if c == "All" else label(c))
    keyword = st.text_input("Title keyword (optional)")
    if st.button("Fetch & index"):
        if not os.getenv("SAM_API_KEY"):
            st.error("Set SAM_API_KEY in .env")
        else:
            with st.spinner("Calling SAM.gov..."):
                try:
                    opps = sam_client.fetch_opportunities(
                        days, limit, None if f_naics == "All" else f_naics, keyword or None)
                    st.success(f"{len(opps)} notices -> {rag.index_opportunities(opps)} chunks")
                    st.rerun()
                except Exception as e:
                    st.error(f"SAM.gov error: {e}")

    st.header("Retrieval")
    top_k = st.slider("Chunks to retrieve (k)", 2, 20, 12)
    open_only = st.checkbox("Only open notices (deadline not passed)", value=True)
    naics_filter = st.selectbox("Restrict answers to NAICS", ["All"] + list(NAICS_TITLES),
                                format_func=lambda c: c if c == "All" else label(c))

rows = rag.list_notices(open_only)
with st.expander(f"Browse indexed notices, sorted by deadline ({len(rows)} shown)"):
    if rows:
        st.dataframe(
            [{"Deadline": (m.get("deadline") or "N/A")[:10], "Title": m["title"],
              "Agency": m["agency"], "NAICS": m["naics"], "PSC": m.get("psc", ""),
              "Set-aside": m["set_aside"], "Link": m["url"]} for m in rows],
            column_config={"Link": st.column_config.LinkColumn("Link")},
            hide_index=True, use_container_width=True)
    else:
        st.write("No notices to show.")

if rows:
    with st.expander("Stats: top agencies by open notices"):
        import pandas as pd
        counts = {}
        for m in rows:
            dept = (m["agency"] or "Unknown").split(".")[0].title()
            counts[dept] = counts.get(dept, 0) + 1
        top = sorted(counts.items(), key=lambda x: -x[1])[:10]
        st.bar_chart(pd.Series(dict(top)))

if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("sources"):
            with st.expander("Sources"):
                for i, s in enumerate(m["sources"], 1):
                    st.markdown(f"**[{i}]** [{s['meta']['title']}]({s['meta']['url']}) - "
                                f"{s['meta']['agency']} | NAICS {s['meta']['naics']} | "
                                f"deadline {s['meta']['deadline'][:10] or 'N/A'}")

if prompt := st.chat_input("e.g. Which small-business set-aside notices are due soonest?"):
    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    last = st.session_state.messages[-1] if st.session_state.messages else {}
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", last.get("content", ""))}
    srcs = last.get("sources", [])
    prev_ids = list({srcs[n - 1]["meta"]["notice_id"] for n in cited if 0 < n <= len(srcs)})
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Searching notices..."):
            reply, sources = rag.answer(prompt, history, top_k,
                                        None if naics_filter == "All" else naics_filter, open_only, prev_ids)
        st.markdown(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply, "sources": sources})
    st.rerun()