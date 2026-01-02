# app.py
import os
import re
import sqlite3
from typing import List, Tuple

import pandas as pd
import streamlit as st

# -----------------------------
# Config
# -----------------------------
DATA_FOLDER = "data"          # must match your GitHub folder name exactly
DB_NAME = "mrts.db"           # must match your DB filename exactly
DB_PATH = os.path.join(DATA_FOLDER, DB_NAME)

STOPWORDS = {
    "what", "how", "when", "where", "why", "who",
    "is", "are", "was", "were", "do", "does", "did",
    "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "at", "by",
    "between", "into", "within", "from", "as", "it", "this", "that", "these", "those",
    "required", "requirement", "requirements",
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
    # de-duplicate keep order
    out, seen = [], set()
    for t in tokens:
        if t not in seen:
            out.append(t)
            seen.add(t)
    return out

def extract_table_or_clause_ref(q: str) -> str:
    """
    If user types Table 9.4.2.3 or Clause 9.2.1, pull out 9.4.2.3 etc.
    """
    q = (q or "").lower()
    m = re.search(r"(?:table|clause)\s*([0-9]+(?:\.[0-9]+)*)", q)
    return m.group(1) if m else ""

@st.cache_resource(show_spinner=False)
def get_conn():
    # Streamlit Cloud can read SQLite from repo file system
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def get_mrts_list(conn) -> List[str]:
    rows = conn.execute(
        "SELECT DISTINCT mrts FROM clauses UNION SELECT DISTINCT mrts FROM tables ORDER BY mrts"
    ).fetchall()
    return [r[0] for r in rows if r and r[0]]

def build_like_where(column: str, tokens: List[str], require_all: bool) -> Tuple[str, List[str]]:
    """
    Returns (sql_where, params) for LIKE token search.
    """
    if not tokens:
        return "1=1", []
    parts, params = [], []
    joiner = " AND " if require_all else " OR "
    for tok in tokens:
        parts.append(f"LOWER({column}) LIKE ?")
        params.append(f"%{tok.lower()}%")
    return "(" + joiner.join(parts) + ")", params

def query_clauses(conn, mrts: str, query: str, require_all: bool, limit: int = 20) -> pd.DataFrame:
    tokens = tokenize(query)
    ref = extract_table_or_clause_ref(query)

    where_text, params_text = build_like_where("text", tokens, require_all)

    where = [where_text]
    params = list(params_text)

    if mrts != "All MRTS":
        where.append("UPPER(mrts) = ?")
        params.append(mrts.upper())

    # boost exact clause/table ref if provided
    boost_sql = "0"
    if ref:
        boost_sql = "CASE WHEN clause_id LIKE ? OR clause_title LIKE ? OR title LIKE ? THEN 3 ELSE 0 END"
        params = ([f"%{ref}%"] * 3) + params

    # score = number of matched tokens + boost
    score_parts = []
    score_params = []
    for tok in tokens:
        score_parts.append("CASE WHEN LOWER(text) LIKE ? THEN 1 ELSE 0 END")
        score_params.append(f"%{tok.lower()}%")

    score_sql = " + ".join(score_parts) if score_parts else "0"
    score_sql = f"({score_sql}) + ({boost_sql})"

    sql = f"""
        SELECT
          mrts, doc_title, rev_date,
          clause_id, clause_title, title,
          pages, page_start, page_end,
          text,
          {score_sql} AS score
        FROM clauses
        WHERE {" AND ".join(where)}
        ORDER BY score DESC, mrts ASC, clause_id ASC
        LIMIT {int(limit)}
    """

    # IMPORTANT: params order must match SQL:
    # score_params first (for score token checks), then boost params (if any), then where params
    final_params = score_params + params
    df = pd.read_sql_query(sql, conn, params=final_params)
    return df

def query_tables(conn, mrts: str, query: str, require_all: bool, limit: int = 25) -> pd.DataFrame:
    tokens = tokenize(query)
    ref = extract_table_or_clause_ref(query)

    # Search across multiple columns, but keep it simple
    search_blob_cols = "COALESCE(caption,'') || ' ' || COALESCE(parameter,'') || ' ' || COALESCE(value,'') || ' ' || COALESCE(units,'') || ' ' || COALESCE(notes,'') || ' ' || COALESCE(table_text,'') || ' ' || COALESCE(table_id,'')"
    where_text, params_text = build_like_where(search_blob_cols, tokens, require_all)

    where = [where_text]
    params = list(params_text)

    if mrts != "All MRTS":
        where.append("UPPER(mrts) = ?")
        params.append(mrts.upper())

    boost_sql = "0"
    boost_params = []
    if ref:
        boost_sql = "CASE WHEN table_id LIKE ? OR caption LIKE ? THEN 3 ELSE 0 END"
        boost_params = [f"%{ref}%", f"%{ref}%"]

    score_parts = []
    score_params = []
    for tok in tokens:
        score_parts.append(f"CASE WHEN LOWER({search_blob_cols}) LIKE ? THEN 1 ELSE 0 END")
        score_params.append(f"%{tok.lower()}%")

    score_sql = " + ".join(score_parts) if score_parts else "0"
    score_sql = f"({score_sql}) + ({boost_sql})"

    sql = f"""
        SELECT
          mrts, doc_title, rev_date,
          table_id, caption, page, pages,
          parameter, value, units, notes, table_text,
          {score_sql} AS score
        FROM tables
        WHERE {" AND ".join(where)}
        ORDER BY score DESC, mrts ASC, table_id ASC
        LIMIT {int(limit)}
    """

    final_params = score_params + boost_params + params
    df = pd.read_sql_query(sql, conn, params=final_params)
    return df


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="MRTS Reference Viewer (QLD) — SQLite", layout="wide")
st.title("MRTS Reference Viewer (QLD) — SQLite")
st.caption("SQLite-backed MRTS reference. Better than CSV search. Always verify against official MRTS.")

# Guardrails
if not os.path.isdir(DATA_FOLDER):
    st.error(f"Folder not found: `{DATA_FOLDER}`. Create it in GitHub and upload `mrts.db` inside it.")
    st.stop()

if not os.path.isfile(DB_PATH):
    st.error(f"Database not found: `{DB_PATH}`. Upload `mrts.db` into `{DATA_FOLDER}/`.")
    st.stop()

conn = get_conn()

mrts_list = ["All MRTS"] + get_mrts_list(conn)
selected_mrts = st.selectbox("Select MRTS", mrts_list, index=0)

query = st.text_input(
    "Search (examples: asphalt thickness tolerance, Table 9.4.2.3, rolling temperature)",
    value="",
)

require_all = st.checkbox("Require ALL key words (recommended)", value=True)

if not query.strip():
    st.info("Type a search to see results. Tip: use technical words or table numbers (e.g., 'Table 9.2.1', 'rolling temperature').")
    st.stop()

# Fetch results
clauses_df = query_clauses(conn, selected_mrts, query, require_all=require_all, limit=20)
tables_df  = query_tables(conn, selected_mrts, query, require_all=require_all, limit=25)

tab1, tab2 = st.tabs(["Clauses (ranked)", "Tables / OCR (ranked)"])

with tab1:
    if clauses_df.empty:
        st.warning("No clause results found.")
    else:
        st.caption(f"Showing {len(clauses_df)} clause results (ranked).")
        for _, r in clauses_df.iterrows():
            clause_id = norm(r.get("clause_id", ""))
            clause_title = norm(r.get("clause_title", ""))
            mrts = norm(r.get("mrts", ""))
            header = f"{mrts}  {clause_id} — {clause_title}".strip()

            with st.expander(header, expanded=False):
                pages = norm(r.get("pages", ""))
                if not pages:
                    ps = norm(r.get("page_start", ""))
                    pe = norm(r.get("page_end", ""))
                    pages = f"{ps}-{pe}".strip("-")

                meta = []
                if pages:
                    meta.append(f"Pages: {pages}")
                rev = norm(r.get("rev_date", ""))
                if rev:
                    meta.append(f"Revision: {rev}")
                doc = norm(r.get("doc_title", ""))
                if doc:
                    meta.append(f"Doc: {doc}")
                score = r.get("score", "")
                meta.append(f"Score: {score}")

                st.caption(" | ".join(meta))
                st.write(norm(r.get("text", "")))

with tab2:
    if tables_df.empty:
        st.warning("No table/OCR results found.")
    else:
        st.caption(f"Showing {len(tables_df)} table/OCR results (ranked).")
        for _, r in tables_df.iterrows():
            table_id = norm(r.get("table_id", ""))
            caption = norm(r.get("caption", ""))
            mrts = norm(r.get("mrts", ""))
            header = f"{mrts}  {table_id} — {caption}".strip()

            with st.expander(header, expanded=False):
                pages = norm(r.get("pages", "")) or norm(r.get("page", ""))
                meta = []
                if pages:
                    meta.append(f"Pages: {pages}")
                rev = norm(r.get("rev_date", ""))
                if rev:
                    meta.append(f"Revision: {rev}")
                doc = norm(r.get("doc_title", ""))
                if doc:
                    meta.append(f"Doc: {doc}")
                score = r.get("score", "")
                meta.append(f"Score: {score}")

                st.caption(" | ".join(meta))

                st.write("**Extracted fields**")
                st.json({
                    "parameter": norm(r.get("parameter", "")),
                    "value": norm(r.get("value", "")),
                    "units": norm(r.get("units", "")),
                    "notes": norm(r.get("notes", "")),
                })

                table_text = norm(r.get("table_text", ""))
                if table_text:
                    st.write("**Table/OCR text**")
                    st.write(table_text)