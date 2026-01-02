# app.py (SQLite MRTS - grouped + table rendering)
import os
import re
import sqlite3
from typing import List, Optional

import pandas as pd
import streamlit as st

DATA_DIR = "data"
DB_FILE = "mrts.db"
DB_PATH = os.path.join(DATA_DIR, DB_FILE)

STOPWORDS = {
    "what","how","when","where","why","who",
    "is","are","was","were","do","does","did",
    "the","a","an","and","or","to","for","of","in","on","at","by",
    "between","into","within","from","as","it","this","that","these","those",
    "show","tell","give","please","required","requirement","requirements",
    "min","minimum","max","maximum"
}

def norm(s: str) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize(q: str) -> List[str]:
    q = norm(q).lower()
    raw = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)*", q)
    tokens = [t for t in raw if t not in STOPWORDS and len(t) >= 2]
    # de-dup keep order
    out, seen = [], set()
    for t in tokens:
        if t not in seen:
            out.append(t)
            seen.add(t)
    return out

def build_fts_query(tokens: List[str], require_all: bool) -> str:
    if not tokens:
        return ""
    joiner = " AND " if require_all else " OR "
    safe = [f'"{t.replace(chr(34), "")}"' for t in tokens]
    return joiner.join(safe)

def has_table(conn: sqlite3.Connection, name: str) -> bool:
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,)
    ).fetchone()
    return r is not None

def looks_like_pipe_table(txt: str) -> bool:
    # crude detector: at least 2 lines with pipes and a separator row
    if not txt:
        return False
    lines = [l.strip() for l in txt.strip().splitlines() if l.strip()]
    if len(lines) < 3:
        return False
    pipe_lines = [l for l in lines if "|" in l]
    if len(pipe_lines) < 2:
        return False
    # separator like |---|---|
    sep = any(re.search(r"\|\s*:?-{2,}:?\s*\|", l) for l in lines)
    return sep

def render_table_value_text(value_text: str, detailed: bool):
    """
    Show table in a readable way.
    - If it looks like a markdown pipe table -> render as markdown
    - Else -> show as wrapped text, and optionally raw block
    """
    vt = value_text or ""
    vt = vt.strip()

    if not vt:
        st.info("No table content found in database for this table.")
        return

    if looks_like_pipe_table(vt):
        # Streamlit renders markdown tables well
        st.markdown(vt)
        if detailed:
            with st.expander("Show raw table text"):
                st.code(vt)
    else:
        # Not a clean pipe table – still show nicely
        if detailed:
            st.write(vt)
            with st.expander("Show raw OCR/text"):
                st.code(vt)
        else:
            # simple view: preview first ~600 chars
            preview = vt[:600] + ("…" if len(vt) > 600 else "")
            st.write(preview)
            with st.expander("Show full text"):
                st.write(vt)

@st.cache_resource(show_spinner=False)
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

@st.cache_data(show_spinner=False)
def get_mrts_list() -> List[str]:
    conn = get_conn()
    try:
        mrts = set()
        if has_table(conn, "clauses"):
            mrts |= set(r[0] for r in conn.execute("SELECT DISTINCT mrts FROM clauses").fetchall() if r and r[0])
        if has_table(conn, "tables"):
            mrts |= set(r[0] for r in conn.execute("SELECT DISTINCT mrts FROM tables").fetchall() if r and r[0])
        return sorted(mrts)
    finally:
        conn.close()

def search_clauses(conn, mrts_filter: str, query: str, require_all: bool, limit: int):
    if not has_table(conn, "clauses") or not has_table(conn, "clauses_fts"):
        return pd.DataFrame()

    tokens = tokenize(query)
    if not tokens:
        return pd.DataFrame()

    fts_q = build_fts_query(tokens, require_all)

    sql = """
    SELECT
      c.mrts, c.revision, c.clause_id, c.title, c.text, c.page_start, c.page_end,
      bm25(clauses_fts) AS rank
    FROM clauses_fts
    JOIN clauses c ON c.rowid = clauses_fts.rowid
    WHERE clauses_fts MATCH ?
    """
    params = [fts_q]
    if mrts_filter != "All MRTS":
        sql += " AND UPPER(c.mrts)=UPPER(?) "
        params.append(mrts_filter)

    sql += " ORDER BY rank LIMIT ?"
    params.append(int(limit))

    return pd.read_sql_query(sql, conn, params=params)

def search_tables(conn, mrts_filter: str, query: str, require_all: bool, limit: int):
    if not has_table(conn, "tables") or not has_table(conn, "tables_fts"):
        return pd.DataFrame()

    tokens = tokenize(query)
    if not tokens:
        return pd.DataFrame()

    fts_q = build_fts_query(tokens, require_all)

    sql = """
    SELECT
      t.mrts, t.revision, t.page, t.table_id, t.caption, t.value_text,
      bm25(tables_fts) AS rank
    FROM tables_fts
    JOIN tables t ON t.rowid = tables_fts.rowid
    WHERE tables_fts MATCH ?
    """
    params = [fts_q]
    if mrts_filter != "All MRTS":
        sql += " AND UPPER(t.mrts)=UPPER(?) "
        params.append(mrts_filter)

    sql += " ORDER BY rank LIMIT ?"
    params.append(int(limit))

    return pd.read_sql_query(sql, conn, params=params)

def group_tables(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group multiple hits from same table into one row.
    Keep best rank (lowest number) and concatenate pages if needed.
    """
    if df is None or df.empty:
        return df

    df = df.copy()
    df["table_id"] = df["table_id"].fillna("").astype(str)
    df["caption"] = df["caption"].fillna("").astype(str)
    df["page"] = df["page"].fillna("").astype(str)
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")

    # group key: mrts + table_id + caption
    gcols = ["mrts", "table_id", "caption"]

    # best row per group = lowest rank
    df_sorted = df.sort_values("rank", ascending=True)

    rows = []
    for key, g in df_sorted.groupby(gcols, dropna=False):
        best = g.iloc[0].to_dict()
        # merge pages
        pages = sorted(set([p for p in g["page"].tolist() if p.strip()]))
        best["pages_merged"] = ", ".join(pages[:10]) + ("…" if len(pages) > 10 else "")
        rows.append(best)

    out = pd.DataFrame(rows)
    out = out.sort_values("rank", ascending=True)
    return out


# ---------------- UI ----------------
st.set_page_config(page_title="MRTS Search (SQLite)", layout="wide")
st.title("MRTS Search (SQLite)")
st.caption("Grouped results + readable table rendering. Always verify against official MRTS PDFs.")

# Folder checks
if not os.path.isdir(DATA_DIR):
    st.error(f"Missing folder `{DATA_DIR}`. Create `{DATA_DIR}/` and upload `{DB_FILE}` inside it.")
    st.stop()

if not os.path.isfile(DB_PATH):
    st.error(f"Missing database `{DB_PATH}`. Upload your `{DB_FILE}` into `{DATA_DIR}/`.")
    st.stop()

mrts_list = get_mrts_list()
mrts_options = ["All MRTS"] + (mrts_list if mrts_list else [])
selected_mrts = st.selectbox("Select MRTS", mrts_options, index=1 if len(mrts_options) > 1 else 0)

query = st.text_input("Search (e.g., air voids, Table 9.2.1, rolling temperature, thickness tolerance)", value="")

colA, colB, colC = st.columns([1,1,1])
with colA:
    require_all = st.checkbox("Require ALL key words", value=True)
with colB:
    detailed_view = st.checkbox("Detailed view", value=False)
with colC:
    max_results = st.selectbox("Max results", [10, 20, 30, 50], index=1)

if not query.strip():
    st.info("Type a search to see results. Tip: include MRTS table numbers like 'Table 9.2.1' or key words like 'air voids'.")
    st.stop()

conn = get_conn()
try:
    clauses_df = search_clauses(conn, selected_mrts, query, require_all, limit=max_results)
    tables_df = search_tables(conn, selected_mrts, query, require_all, limit=max_results * 2)
finally:
    conn.close()

tables_grouped = group_tables(tables_df)

tab1, tab2 = st.tabs(["Clauses (grouped, ranked)", "Tables (grouped, readable)"])

with tab1:
    if clauses_df is None or clauses_df.empty:
        st.warning("No clause results found.")
    else:
        st.caption(f"Top clause results: {min(len(clauses_df), max_results)}")
        for _, r in clauses_df.head(max_results).iterrows():
            header = f"{r.get('mrts','')}  {r.get('clause_id','')} — {norm(r.get('title',''))}"
            with st.expander(header, expanded=False):
                pages = f"{r.get('page_start','')}-{r.get('page_end','')}".strip("-")
                meta = []
                if pages:
                    meta.append(f"Pages: {pages}")
                if r.get("revision",""):
                    meta.append(f"Revision: {r.get('revision')}")
                meta.append(f"Rank: {r.get('rank')}")
                st.caption(" | ".join(meta))

                txt = norm(r.get("text",""))
                if not detailed_view and len(txt) > 900:
                    st.write(txt[:900] + "…")
                    with st.expander("Show full clause text"):
                        st.write(txt)
                else:
                    st.write(txt)

with tab2:
    if tables_grouped is None or tables_grouped.empty:
        st.warning("No table results found.")
    else:
        st.caption(f"Grouped tables: {min(len(tables_grouped), max_results)}")
        for _, r in tables_grouped.head(max_results).iterrows():
            header = f"{r.get('mrts','')}  {r.get('table_id','')} — {norm(r.get('caption',''))}"
            with st.expander(header, expanded=False):
                meta = []
                if r.get("pages_merged",""):
                    meta.append(f"Pages: {r.get('pages_merged')}")
                if r.get("revision",""):
                    meta.append(f"Revision: {r.get('revision')}")
                meta.append(f"Rank: {r.get('rank')}")
                st.caption(" | ".join(meta))

                render_table_value_text(r.get("value_text",""), detailed=detailed_view)