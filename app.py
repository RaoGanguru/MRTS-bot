# app.py (SQLite MRTS - grouped + table rendering)
# app.py (SQLite MRTS - grouped + table rendering) - improved table parsing + fixed DB connection handling
import os
import re
import io
import csv
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
    s = s.replace("\r", " ")
    # keep newlines for table parsing/rendering where appropriate, but normalize sequences of whitespace
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)  # collapse multiple blank lines
    s = s.strip()
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
    # improved detection: check for at least one line with '|' and a separator line after header
    if not txt:
        return False
    lines = [l.rstrip() for l in txt.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return False
    # at least one '|' in most lines
    pipe_count = sum(1 for l in lines if "|" in l)
    if pipe_count < 2:
        return False
    # separator like |---|---| or ---|--- or :---:
    sep_re = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
    for i in range(1, min(len(lines), 4)):
        if sep_re.match(lines[i]):
            return True
    return False

def parse_pipe_table(txt: str) -> Optional[pd.DataFrame]:
    """
    Parse a Markdown-style pipe table into a DataFrame.
    Handles optional leading/trailing '|' and a separator line with dashes.
    """
    lines = [l.rstrip() for l in txt.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return None

    # find header and separator line indices
    sep_idx = None
    sep_re = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
    for i in range(1, min(len(lines), 4)):
        if sep_re.match(lines[i]):
            sep_idx = i
            break

    if sep_idx is None:
        # Try lenient parse: treat first line as header and split on '|'
        header_line = lines[0]
        data_lines = lines[1:]
    else:
        header_line = lines[0]
        data_lines = lines[sep_idx+1:]

    def split_row(line: str) -> List[str]:
        # remove leading/trailing pipes, split on '|' and strip each cell
        row = line.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        cells = [c.strip() for c in row.split("|")]
        return cells

    header = split_row(header_line)
    rows = [split_row(l) for l in data_lines if l.strip()]
    # Normalize row length by padding/trimming
    maxcols = max(len(header), max((len(r) for r in rows), default=0))
    header = (header + [""] * maxcols)[:maxcols]
    norm_rows = [ (r + [""] * maxcols)[:maxcols] for r in rows ]

    try:
        df = pd.DataFrame(norm_rows, columns=header)
        return df
    except Exception:
        return None

def parse_table_text(value_text: str) -> Optional[pd.DataFrame]:
    """
    Try multiple strategies to parse a table-like text into a DataFrame:
     1) HTML table via pandas.read_html
     2) Markdown pipe table parser
     3) CSV/TSV via csv.Sniffer -> pandas.read_csv
     4) Fixed-width via pandas.read_fwf
    Return DataFrame on success, otherwise None.
    """
    vt = (value_text or "").strip()
    if not vt:
        return None

    # 1) try HTML table(s)
    try:
        dfs = pd.read_html(vt)
        if dfs and len(dfs) > 0:
            return dfs[0]
    except Exception:
        pass

    # 2) markdown pipe table
    try:
        if looks_like_pipe_table(vt):
            df = parse_pipe_table(vt)
            if df is not None and not df.empty:
                return df
    except Exception:
        pass

    # 3) CSV / TSV detection using csv.Sniffer
    try:
        sample = "\n".join(vt.splitlines()[:10])
        sniffer = csv.Sniffer()
        # try to detect delimiter; fall back to comma if detection fails
        dialect = None
        try:
            dialect = sniffer.sniff(sample)
        except Exception:
            # fallback: if there are tabs, use '\t', else if pipes present, use '|', else use ','
            if "\t" in sample:
                dialect = csv.get_dialect("excel")
                dialect.delimiter = "\t"
            elif "|" in sample:
                dialect = csv.get_dialect("excel")
                dialect.delimiter = "|"
            else:
                dialect = csv.get_dialect("excel")
                dialect.delimiter = ","

        delim = dialect.delimiter if dialect else ","
        df = pd.read_csv(io.StringIO(vt), sep=delim)
        if not df.empty:
            return df
    except Exception:
        pass

    # 4) try fixed-width
    try:
        df = pd.read_fwf(io.StringIO(vt))
        if not df.empty:
            return df
    except Exception:
        pass

    return None

def render_table_value_text(value_text: str, detailed: bool):
    """
    Show table in a readable way.
    - Try to parse into DataFrame and render via st.dataframe/st.table
    - Else if it looks like a markdown pipe table -> render as markdown
    - Else -> show as wrapped text, and optionally raw block
    """
    vt = value_text or ""
    vt = vt.strip()

    if not vt:
        st.info("No table content found in database for this table.")
        return

    # Attempt to parse to DataFrame first
    df = parse_table_text(vt)
    if df is not None and not df.empty:
        # Render dataframe: dataframes keep column order and types
        st.dataframe(df, use_container_width=True)
        # Provide CSV download
        try:
            csv_bytes = df.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", data=csv_bytes, file_name="table.csv", mime="text/csv")
        except Exception:
            pass
        if detailed:
            with st.expander("Show raw table text"):
                st.code(vt)
        return

    # If parsing failed but looks like a pipe table, render as markdown (best-effort)
    if looks_like_pipe_table(vt):
        st.markdown(vt)
        if detailed:
            with st.expander("Show raw table text"):
                st.code(vt)
        return

    # Not a clean table – still show nicely
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
    # cached long-lived connection for the Streamlit app lifetime
    return sqlite3.connect(DB_PATH, check_same_thread=False)

@st.cache_data(show_spinner=False)
def get_mrts_list() -> List[str]:
    # Use a fresh connection here so we can safely close it,
    # without touching the cached connection returned by get_conn().
    conn = sqlite3.connect(DB_PATH)
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

# Use the cached connection but do NOT close it manually.
conn = get_conn()
clauses_df = search_clauses(conn, selected_mrts, query, require_all, limit=max_results)
tables_df = search_tables(conn, selected_mrts, query, require_all, limit=max_results * 2)

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
