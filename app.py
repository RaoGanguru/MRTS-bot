import os
import re
import sqlite3
from typing import List

import pandas as pd
import streamlit as st

DB_PATH = os.path.join("data", "mrts.db")

STOPWORDS = {
    "what", "how", "when", "where", "why", "who",
    "is", "are", "was", "were", "do", "does", "did",
    "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "at", "by",
    "between", "into", "within", "from", "as", "it", "this", "that", "these", "those",
    "show", "tell", "give", "please",
}

def norm(s: str) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize(q: str) -> List[str]:
    q = norm(q).lower()
    # keep clause numbers like 9.2.1(a), 9.4.2.3, Table 8.8
    raw = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)*|\d+\([a-z]\)", q)
    tokens = [t for t in raw if t not in STOPWORDS and len(t) >= 2]
    # de-dup keep order
    seen = set()
    out = []
    for t in tokens:
        if t not in seen:
            out.append(t)
            seen.add(t)
    return out

def has_table(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (name,))
    return cur.fetchone() is not None

def has_fts(conn: sqlite3.Connection) -> bool:
    # We expect these from build_db.py / the provided mrts.db
    return has_table(conn, "clauses_fts") and has_table(conn, "tables_fts")

def build_fts_query(tokens: List[str], require_all: bool) -> str:
    """
    FTS5 query:
      - require_all=True  => token1 AND token2 AND ...
      - require_all=False => token1 OR token2 OR ...
    We quote tokens to reduce parser surprises (esp. numbers with dots).
    """
    if not tokens:
        return ""
    joiner = " AND " if require_all else " OR "
    safe = []
    for t in tokens:
        t = t.replace('"', "")
        safe.append(f'"{t}"')
    return joiner.join(safe)

@st.cache_data(show_spinner=False)
def get_mrts_list() -> List[str]:
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    try:
        # try clauses table first, then tables
        mrts = set()
        for tbl in ["clauses", "tables"]:
            if has_table(conn, tbl):
                rows = conn.execute(f"SELECT DISTINCT mrts FROM {tbl} WHERE mrts IS NOT NULL AND TRIM(mrts) <> ''").fetchall()
                mrts |= set(r[0] for r in rows if r and r[0])
        return sorted(mrts)
    finally:
        conn.close()

def query_clauses(conn: sqlite3.Connection, mrts_filter: str, tokens: List[str], require_all: bool, limit: int = 20):
    if not has_table(conn, "clauses"):
        return pd.DataFrame()

    if has_fts(conn) and tokens:
        fts_q = build_fts_query(tokens, require_all)
        sql = """
        SELECT c.mrts, c.clause_id, c.clause_title, c.text, c.pages, c.page_start, c.page_end,
               bm25(clauses_fts) AS rank
        FROM clauses_fts
        JOIN clauses c ON c.rowid = clauses_fts.rowid
        WHERE clauses_fts MATCH ?
        """
        params = [fts_q]
        if mrts_filter != "All MRTS":
            sql += " AND UPPER(c.mrts) = UPPER(?) "
            params.append(mrts_filter)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        df = pd.read_sql_query(sql, conn, params=params)
        # bm25: lower is better (more relevant)
        return df

    # Fallback: LIKE search (worse but safe)
    q = " ".join(tokens).strip()
    if not q:
        return pd.DataFrame()
    sql = """
    SELECT mrts, clause_id, clause_title, text, pages, page_start, page_end
    FROM clauses
    WHERE (LOWER(text) LIKE ? OR LOWER(clause_title) LIKE ? OR LOWER(clause_id) LIKE ?)
    """
    like = f"%{q.lower()}%"
    params = [like, like, like]
    if mrts_filter != "All MRTS":
        sql += " AND UPPER(mrts) = UPPER(?) "
        params.append(mrts_filter)
    sql += " LIMIT ?"
    params.append(limit)
    return pd.read_sql_query(sql, conn, params=params)

def query_tables(conn: sqlite3.Connection, mrts_filter: str, tokens: List[str], require_all: bool, limit: int = 30):
    if not has_table(conn, "tables"):
        return pd.DataFrame()

    if has_fts(conn) and tokens:
        fts_q = build_fts_query(tokens, require_all)
        sql = """
        SELECT t.mrts, t.table_id, t.caption, t.parameter, t.value, t.units, t.notes, t.table_text, t.page, t.pages,
               bm25(tables_fts) AS rank
        FROM tables_fts
        JOIN tables t ON t.rowid = tables_fts.rowid
        WHERE tables_fts MATCH ?
        """
        params = [fts_q]
        if mrts_filter != "All MRTS":
            sql += " AND UPPER(t.mrts) = UPPER(?) "
            params.append(mrts_filter)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        df = pd.read_sql_query(sql, conn, params=params)
        return df

    # Fallback: LIKE search
    q = " ".join(tokens).strip()
    if not q:
        return pd.DataFrame()
    sql = """
    SELECT mrts, table_id, caption, parameter, value, units, notes, table_text, page, pages
    FROM tables
    WHERE (
        LOWER(COALESCE(table_text,'')) LIKE ?
        OR LOWER(COALESCE(caption,'')) LIKE ?
        OR LOWER(COALESCE(table_id,'')) LIKE ?
        OR LOWER(COALESCE(parameter,'')) LIKE ?
        OR LOWER(COALESCE(value,'')) LIKE ?
    )
    """
    like = f"%{q.lower()}%"
    params = [like, like, like, like, like]
    if mrts_filter != "All MRTS":
        sql += " AND UPPER(mrts) = UPPER(?) "
        params.append(mrts_filter)
    sql += " LIMIT ?"
    params.append(limit)
    return pd.read_sql_query(sql, conn, params=params)

# ---------------- UI ----------------
st.set_page_config(page_title="MRTS Bot (SQLite)", layout="wide")
st.title("MRTS Bot (SQLite)")
st.caption("Fast search using SQLite. Shows clause/table text with page references. Always verify in the official PDF.")

if not os.path.exists(DB_PATH):
    st.error("Database not found. Please upload `data/mrts.db` to your GitHub repo.")
    st.stop()

mrts_list = get_mrts_list()
mrts_options = ["All MRTS"] + (mrts_list if mrts_list else [])
selected_mrts = st.selectbox("Select MRTS", mrts_options, index=1 if len(mrts_options) > 1 else 0)

query = st.text_input("Search (e.g., 'asphalt thickness tolerance', 'Table 9.2.1', 'rolling temperature')", value="")
require_all = st.checkbox("Require ALL key words (recommended)", value=True)

# Extra control to reduce rubbish results
only_this_mrts_default = selected_mrts != "All MRTS"
only_this_mrts = st.checkbox("Restrict results to selected MRTS only", value=only_this_mrts_default)

effective_mrts = selected_mrts if only_this_mrts else "All MRTS"

tokens = tokenize(query)

if not query.strip():
    st.info("Type a search. Tip: include the subject words (asphalt / tolerance / temperature / air voids / Table 9.2.1 etc.).")
    st.stop()

conn = sqlite3.connect(DB_PATH)
try:
    clauses_df = query_clauses(conn, effective_mrts, tokens, require_all=require_all, limit=20)
    tables_df = query_tables(conn, effective_mrts, tokens, require_all=require_all, limit=30)
finally:
    conn.close()

tab1, tab2 = st.tabs(["Clauses", "Tables / OCR"])

with tab1:
    if clauses_df is None or clauses_df.empty:
        st.warning("No clause results found.")
    else:
        st.caption(f"Top {min(20, len(clauses_df))} clause results.")
        for _, r in clauses_df.head(20).iterrows():
            mrts = r.get("mrts","")
            cid = r.get("clause_id","")
            title = r.get("clause_title","")
            pages = r.get("pages","") or ""
            if not pages:
                ps = r.get("page_start","")
                pe = r.get("page_end","")
                if ps or pe:
                    pages = f"{ps}-{pe}".strip("-")
            header = f"{mrts}  {cid} — {title}"
            with st.expander(header, expanded=False):
                if pages:
                    st.caption(f"Pages: {pages}")
                st.write(norm(r.get("text","")))

with tab2:
    if tables_df is None or tables_df.empty:
        st.warning("No table/OCR results found.")
    else:
        st.caption(f"Top {min(30, len(tables_df))} table results.")
        for _, r in tables_df.head(30).iterrows():
            mrts = r.get("mrts","")
            tid = r.get("table_id","")
            cap = r.get("caption","")
            page = r.get("page","") or r.get("pages","")
            header = f"{mrts}  {tid} — {cap}"
            with st.expander(header, expanded=False):
                if page:
                    st.caption(f"Pages: {page}")

                # show extracted fields (if present)
                row = {
                    "parameter": norm(r.get("parameter","")),
                    "value": norm(r.get("value","")),
                    "units": norm(r.get("units","")),
                    "notes": norm(r.get("notes","")),
                }
                if any(v for v in row.values()):
                    st.write("**Extracted fields**")
                    st.json(row)

                ttxt = norm(r.get("table_text",""))
                if ttxt:
                    st.write("**Table/OCR text**")
                    st.write(ttxt)
