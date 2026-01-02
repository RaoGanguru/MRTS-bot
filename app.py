
 
# app.py (SQLite + Requirements-first)
import os
import re
import sqlite3
from typing import List, Tuple

import pandas as pd
import streamlit as st

DATA_FOLDER = "data"
DB_NAME = "mrts.db"
DB_PATH = os.path.join(DATA_FOLDER, DB_NAME)

STOPWORDS = {
    "what","how","when","where","why","who",
    "is","are","was","were","do","does","did",
    "the","a","an","and","or","to","for","of","in","on","at","by",
    "between","into","within","from","as","it","this","that","these","those",
    "show","tell","give","please",
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
    out, seen = [], set()
    for t in tokens:
        if t not in seen:
            out.append(t)
            seen.add(t)
    return out

@st.cache_resource(show_spinner=False)
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def has_table(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None

def get_mrts_list(conn) -> List[str]:
    mrts = set()
    for tbl in ["requirements","clauses","tables"]:
        if has_table(conn, tbl):
            rows = conn.execute(
                f"SELECT DISTINCT mrts FROM {tbl} WHERE mrts IS NOT NULL AND TRIM(mrts)<>''"
            ).fetchall()
            mrts |= set(r[0] for r in rows if r and r[0])
    return sorted(mrts)

def build_like_where(column_expr: str, tokens: List[str], require_all: bool) -> Tuple[str, List[str]]:
    if not tokens:
        return "1=1", []
    joiner = " AND " if require_all else " OR "
    parts, params = [], []
    for tok in tokens:
        parts.append(f"LOWER({column_expr}) LIKE ?")
        params.append(f"%{tok.lower()}%")
    return "(" + joiner.join(parts) + ")", params

def query_requirements(conn, mrts: str, query: str, require_all: bool, limit: int = 40) -> pd.DataFrame:
    if not has_table(conn, "requirements"):
        return pd.DataFrame()

    tokens = tokenize(query)
    blob = "COALESCE(topic,'') || ' ' || COALESCE(parameter,'') || ' ' || COALESCE(conditions,'') || ' ' || COALESCE(source_ref,'') || ' ' || COALESCE(clause_id,'') || ' ' || COALESCE(notes,'')"

    where_blob, params_blob = build_like_where(blob, tokens, require_all)
    where = [where_blob]
    params = list(params_blob)

    if mrts != "All MRTS":
        where.append("UPPER(mrts)=?")
        params.append(mrts.upper())

    score_parts, score_params = [], []
    for tok in tokens:
        score_parts.append(f"CASE WHEN LOWER({blob}) LIKE ? THEN 1 ELSE 0 END")
        score_params.append(f"%{tok.lower()}%")
    score_sql = " + ".join(score_parts) if score_parts else "0"

    sql = f"""
      SELECT mrts, revision, topic, parameter, value_min, value_max, value_text, units,
             conditions, location, layer, thickness_band, limit_type, source_ref, clause_id, page, notes,
             ({score_sql}) AS score
      FROM requirements
      WHERE {' AND '.join(where)}
      ORDER BY score DESC, mrts ASC, topic ASC, parameter ASC
      LIMIT {int(limit)}
    """
    return pd.read_sql_query(sql, conn, params=score_params + params)

def query_clauses(conn, mrts: str, query: str, require_all: bool, limit: int = 20) -> pd.DataFrame:
    if not has_table(conn, "clauses"):
        return pd.DataFrame()

    tokens = tokenize(query)
    blob = "COALESCE(title,'') || ' ' || COALESCE(clause_id,'') || ' ' || COALESCE(text,'')"

    where_blob, params_blob = build_like_where(blob, tokens, require_all)
    where = [where_blob]
    params = list(params_blob)

    if mrts != "All MRTS":
        where.append("UPPER(mrts)=?")
        params.append(mrts.upper())

    score_parts, score_params = [], []
    for tok in tokens:
        score_parts.append(f"CASE WHEN LOWER({blob}) LIKE ? THEN 1 ELSE 0 END")
        score_params.append(f"%{tok.lower()}%")
    score_sql = " + ".join(score_parts) if score_parts else "0"

    sql = f"""
      SELECT mrts, revision, clause_id, title, text, page_start, page_end, ({score_sql}) AS score
      FROM clauses
      WHERE {' AND '.join(where)}
      ORDER BY score DESC, mrts ASC, clause_id ASC
      LIMIT {int(limit)}
    """
    return pd.read_sql_query(sql, conn, params=score_params + params)

def query_tables(conn, mrts: str, query: str, require_all: bool, limit: int = 20) -> pd.DataFrame:
    if not has_table(conn, "tables"):
        return pd.DataFrame()

    tokens = tokenize(query)
    blob = "COALESCE(table_id,'') || ' ' || COALESCE(caption,'') || ' ' || COALESCE(value_text,'')"

    where_blob, params_blob = build_like_where(blob, tokens, require_all)
    where = [where_blob]
    params = list(params_blob)

    if mrts != "All MRTS":
        where.append("UPPER(mrts)=?")
        params.append(mrts.upper())

    score_parts, score_params = [], []
    for tok in tokens:
        score_parts.append(f"CASE WHEN LOWER({blob}) LIKE ? THEN 1 ELSE 0 END")
        score_params.append(f"%{tok.lower()}%")
    score_sql = " + ".join(score_parts) if score_parts else "0"

    sql = f"""
      SELECT mrts, revision, page, table_id, caption, value_text, ({score_sql}) AS score
      FROM tables
      WHERE {' AND '.join(where)}
      ORDER BY score DESC, mrts ASC, table_id ASC
      LIMIT {int(limit)}
    """
    return pd.read_sql_query(sql, conn, params=score_params + params)


# ---------------- UI ----------------
st.set_page_config(page_title="MRTS Viewer — Requirements-first", layout="wide")
st.title("MRTS Viewer — Requirements-first (SQLite)")
st.caption("Shows structured requirements first (temps/tolerances/limits), then clauses/tables as fallback. Always verify in MRTS PDF.")

if not os.path.isdir(DATA_FOLDER):
    st.error(f"Folder not found: `{DATA_FOLDER}`. Create it and upload `{DB_NAME}` inside it.")
    st.stop()

if not os.path.isfile(DB_PATH):
    st.error(f"Database not found: `{DB_PATH}`. Upload `{DB_NAME}` into `{DATA_FOLDER}/`.")
    st.stop()

conn = get_conn()
mrts_options = ["All MRTS"] + get_mrts_list(conn)
selected_mrts = st.selectbox("Select MRTS", mrts_options, index=0)

query = st.text_input("Search (e.g., air voids VL VU, Table 9.2.1, SMA14 texture)", value="")
require_all = st.checkbox("Require ALL key words (recommended)", value=True)

if not query.strip():
    st.info("Type a search. Tip: include subject words (air voids, SMA, texture, tolerance, temperature) or table numbers.")
    st.stop()

req_df = query_requirements(conn, selected_mrts, query, require_all, limit=50)
cla_df = query_clauses(conn, selected_mrts, query, require_all, limit=20)
tab_df = query_tables(conn, selected_mrts, query, require_all, limit=20)

t1, t2, t3 = st.tabs(["Requirements (best)", "Clauses (fallback)", "Tables/OCR (fallback)"])

with t1:
    if req_df.empty:
        st.warning("No structured requirements found yet for this query.")
    else:
        st.caption(f"Showing {len(req_df)} structured requirements.")
        for _, r in req_df.iterrows():
            hdr = f"{r.get('mrts','')} | {r.get('topic','')} | {r.get('parameter','')}"
            with st.expander(hdr, expanded=False):
                st.caption(
                    f"Source: {r.get('source_ref','')} | Clause: {r.get('clause_id','')} | Page: {r.get('page','')} | Rev: {r.get('revision','')}"
                )
                st.json({
                    "value_min": r.get("value_min",""),
                    "value_max": r.get("value_max",""),
                    "value_text": r.get("value_text",""),
                    "units": r.get("units",""),
                    "conditions": r.get("conditions",""),
                    "location": r.get("location",""),
                    "layer": r.get("layer",""),
                    "thickness_band": r.get("thickness_band",""),
                    "limit_type": r.get("limit_type",""),
                    "notes": r.get("notes",""),
                })

with t2:
    if cla_df.empty:
        st.warning("No clause results.")
    else:
        for _, r in cla_df.iterrows():
            hdr = f"{r.get('mrts','')} {r.get('clause_id','')} — {r.get('title','')}"
            with st.expander(hdr, expanded=False):
                pages = f"{r.get('page_start','')}-{r.get('page_end','')}".strip("-")
                st.caption(f"Pages: {pages} | Rev: {r.get('revision','')}")
                st.write(norm(r.get("text","")))

with t3:
    if tab_df.empty:
        st.warning("No table/OCR results.")
    else:
        for _, r in tab_df.iterrows():
            hdr = f"{r.get('mrts','')} {r.get('table_id','')} — {r.get('caption','')}"
            with st.expander(hdr, expanded=False):
                st.caption(f"Page: {r.get('page','')} | Rev: {r.get('revision','')}")
                st.write(norm(r.get("value_text","")))
