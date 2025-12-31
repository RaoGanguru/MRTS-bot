# app.py
import os
import re
from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd
import streamlit as st


# -----------------------------
# Config
# -----------------------------
DATA_FOLDER = "mrts_data"   # must match your GitHub folder name exactly
CLAUSES_SUFFIX = "_structured_clauses.csv"
TABLES_SUFFIX = "_tables_ocr.csv"


# -----------------------------
# Helpers: text + tokenizing
# -----------------------------
STOPWORDS = {
    "what", "how", "when", "where", "why", "who",
    "is", "are", "was", "were", "do", "does", "did",
    "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "at", "by",
    "between", "into", "within", "from", "as", "it", "this", "that", "these", "those",
    "required", "requirement", "requirements",  # often too generic
    "minimum", "maximum",  # keep if you want; but usually generic
}

def norm(s: str) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize(q: str) -> List[str]:
    q = norm(q).lower()
    # keep numbers like 9.4.2.3
    raw = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)*", q)
    # remove stopwords + very short tokens
    tokens = [t for t in raw if t not in STOPWORDS and len(t) >= 2]
    # de-duplicate but keep order
    seen = set()
    out = []
    for t in tokens:
        if t not in seen:
            out.append(t)
            seen.add(t)
    return out

def score_text(text: str, tokens: List[str]) -> Tuple[int, int]:
    """
    Returns (hits, total_tokens) where hits = number of tokens found.
    """
    if not tokens:
        return (0, 0)
    t = (text or "").lower()
    hits = sum(1 for tok in tokens if tok in t)
    return hits, len(tokens)


# -----------------------------
# Loaders
# -----------------------------
def safe_read_csv(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding_errors="ignore")
    except Exception:
        # Try fallback separator (rare)
        try:
            return pd.read_csv(path, dtype=str, keep_default_na=False, sep=";", encoding_errors="ignore")
        except Exception:
            return pd.DataFrame()

def ensure_cols(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    if df is None or len(df) == 0:
        out = pd.DataFrame(columns=cols)
        return out
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = ""
    # force string
    for c in cols:
        out[c] = out[c].fillna("").astype(str)
    return out

@dataclass
class LoadedData:
    clauses: pd.DataFrame
    tables: pd.DataFrame
    mrts_list: List[str]

@st.cache_data(show_spinner=False)
def load_all_data() -> LoadedData:
    clauses_all = []
    tables_all = []

    if not os.path.isdir(DATA_FOLDER):
        return LoadedData(pd.DataFrame(), pd.DataFrame(), [])

    files = os.listdir(DATA_FOLDER)

    for f in files:
        full = os.path.join(DATA_FOLDER, f)

        if f.endswith(CLAUSES_SUFFIX):
            df = safe_read_csv(full)
            df["__source_file"] = f
            clauses_all.append(df)

        if f.endswith(TABLES_SUFFIX):
            df = safe_read_csv(full)
            df["__source_file"] = f
            tables_all.append(df)

    clauses_df = pd.concat(clauses_all, ignore_index=True) if clauses_all else pd.DataFrame()
    tables_df = pd.concat(tables_all, ignore_index=True) if tables_all else pd.DataFrame()

    # Normalize columns we rely on
    clauses_cols = [
        "mrts", "title", "clause_id", "clause_title", "text",
        "page_start", "page_end", "pages", "rev_date", "doc_title"
    ]
    tables_cols = [
        "mrts", "table_id", "caption", "parameter", "value", "units", "notes",
        "table_text", "page", "pages", "rev_date", "doc_title"
    ]
    clauses_df = ensure_cols(clauses_df, clauses_cols + ["__source_file"])
    tables_df = ensure_cols(tables_df, tables_cols + ["__source_file"])

    # Best-effort fill mrts from filename if missing
    def infer_mrts_from_file(fname: str) -> str:
        # e.g. MRTS30_structured_clauses.csv
        m = re.search(r"(MRTS\d+[A-Z0-9]*)", fname.upper())
        return m.group(1) if m else ""

    if "mrts" in clauses_df.columns:
        missing = clauses_df["mrts"].astype(str).str.strip() == ""
        clauses_df.loc[missing, "mrts"] = clauses_df.loc[missing, "__source_file"].apply(infer_mrts_from_file)

    if "mrts" in tables_df.columns:
        missing = tables_df["mrts"].astype(str).str.strip() == ""
        tables_df.loc[missing, "mrts"] = tables_df.loc[missing, "__source_file"].apply(infer_mrts_from_file)

    mrts_set = set()
    if len(clauses_df):
        mrts_set |= set(clauses_df["mrts"].dropna().astype(str).str.strip())
    if len(tables_df):
        mrts_set |= set(tables_df["mrts"].dropna().astype(str).str.strip())

    mrts_list = sorted([m for m in mrts_set if m])

    return LoadedData(clauses_df, tables_df, mrts_list)


# -----------------------------
# Search
# -----------------------------
def search_clauses(df: pd.DataFrame, tokens: List[str], require_all: bool) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    # Create search blob
    blob = (
        df["mrts"].map(norm) + " " +
        df["clause_id"].map(norm) + " " +
        df["clause_title"].map(norm) + " " +
        df["title"].map(norm) + " " +
        df["text"].map(norm)
    ).str.lower()

    hits = []
    for i, txt in enumerate(blob):
        h, n = score_text(txt, tokens)
        if not tokens:
            hits.append(0)
        else:
            if require_all and h != n:
                hits.append(-1)
            else:
                hits.append(h)

    out = df.copy()
    out["_hits"] = hits

    out = out[out["_hits"] >= 0]
    if tokens:
        out = out[out["_hits"] > 0] if not require_all else out
        out["_ratio"] = out["_hits"] / max(len(tokens), 1)
        out = out.sort_values(by=["_ratio", "_hits"], ascending=[False, False])

    return out

def search_tables(df: pd.DataFrame, tokens: List[str], require_all: bool) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    blob = (
        df["mrts"].map(norm) + " " +
        df["table_id"].map(norm) + " " +
        df["caption"].map(norm) + " " +
        df["parameter"].map(norm) + " " +
        df["value"].map(norm) + " " +
        df["units"].map(norm) + " " +
        df["notes"].map(norm) + " " +
        df["table_text"].map(norm) + " " +
        df["page"].map(norm) + " " +
        df["pages"].map(norm)
    ).str.lower()

    hits = []
    for txt in blob:
        h, n = score_text(txt, tokens)
        if not tokens:
            hits.append(0)
        else:
            if require_all and h != n:
                hits.append(-1)
            else:
                hits.append(h)

    out = df.copy()
    out["_hits"] = hits

    out = out[out["_hits"] >= 0]
    if tokens:
        out = out[out["_hits"] > 0] if not require_all else out
        out["_ratio"] = out["_hits"] / max(len(tokens), 1)
        out = out.sort_values(by=["_ratio", "_hits"], ascending=[False, False])

    return out


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="MRTS Reference Viewer (QLD)", layout="wide")

st.title("MRTS Reference Viewer (QLD)")
st.caption("Read-only MRTS reference. Clauses + OCR tables. Verify against official MRTS.")

data = load_all_data()

# If folder missing or no files
if not os.path.isdir(DATA_FOLDER):
    st.error(f"Folder not found: `{DATA_FOLDER}`. Create it in GitHub and upload CSV files there.")
    st.stop()

if (data.clauses.empty) and (data.tables.empty):
    st.warning("No data found yet. Upload CSV files into `mrts_data/`.")
    st.stop()

mrts_options = ["All MRTS"] + (data.mrts_list if data.mrts_list else [])
selected_mrts = st.selectbox("Select MRTS", mrts_options, index=0)

query = st.text_input(
    "Search (examples: asphalt thickness tolerance, Table 9.4.2.3, EME thickness, bitumen temperature)",
    value="",
)

require_all = st.checkbox("Require ALL subject keywords (recommended)", value=True)

# Always define these (prevents NameError)
clauses_f = pd.DataFrame()
tables_f = pd.DataFrame()

tokens = tokenize(query)

# Filter by MRTS selection
clauses_df = data.clauses
tables_df = data.tables

if selected_mrts != "All MRTS":
    clauses_df = clauses_df[clauses_df["mrts"].astype(str).str.upper() == selected_mrts.upper()].copy()
    tables_df = tables_df[tables_df["mrts"].astype(str).str.upper() == selected_mrts.upper()].copy()

# If no query, don't spam results; show small hint
if not query.strip():
    st.info("Type a search to see results. Tip: include the subject words (e.g., 'asphalt thickness tolerance', 'Table 9.4.2.3').")
    st.stop()

# Run searches
clauses_f = search_clauses(clauses_df, tokens, require_all=require_all)
tables_f = search_tables(tables_df, tokens, require_all=require_all)

tab1, tab2 = st.tabs(["Clauses (ranked)", "Tables / OCR (ranked)"])

with tab1:
    if clauses_f is None or clauses_f.empty:
        st.warning("No clause results found.")
    else:
        limit = 15
        st.caption(f"Showing top {min(limit, len(clauses_f))} results.")
        show = clauses_f.head(limit)

        for _, r in show.iterrows():
            header = f"{r.get('mrts','')}  {r.get('clause_id','')} — {r.get('clause_title','')}"
            with st.expander(header, expanded=False):
                meta = []
                pages = r.get("pages", "") or ""
                if not pages:
                    ps = r.get("page_start", "")
                    pe = r.get("page_end", "")
                    if ps or pe:
                        pages = f"{ps}-{pe}".strip("-")
                if pages:
                    meta.append(f"Pages: {pages}")
                rev = r.get("rev_date", "")
                if rev:
                    meta.append(f"Revision: {rev}")
                src = r.get("__source_file", "")
                if src:
                    meta.append(f"Source CSV: {src}")
                if meta:
                    st.caption(" | ".join(meta))

                st.write(norm(r.get("text", "")))

with tab2:
    if tables_f is None or tables_f.empty:
        st.warning("No table/OCR results found.")
    else:
        limit = 25
        st.caption(f"Showing top {min(limit, len(tables_f))} results.")
        show = tables_f.head(limit)

        for _, r in show.iterrows():
            header = f"{r.get('mrts','')}  {r.get('table_id','')} — {r.get('caption','')}"
            with st.expander(header, expanded=False):
                meta = []
                pages = r.get("pages", "") or r.get("page", "")
                if pages:
                    meta.append(f"Pages: {pages}")
                rev = r.get("rev_date", "")
                if rev:
                    meta.append(f"Revision: {rev}")
                src = r.get("__source_file", "")
                if src:
                    meta.append(f"Source CSV: {src}")
                if meta:
                    st.caption(" | ".join(meta))

                # Show structured row if present
                row = {
                    "parameter": norm(r.get("parameter", "")),
                    "value": norm(r.get("value", "")),
                    "units": norm(r.get("units", "")),
                    "notes": norm(r.get("notes", "")),
                }
                st.write("**Extracted fields**")
                st.json(row)

                table_text = norm(r.get("table_text", ""))
                if table_text:
                    st.write("**Table/OCR text**")
                    st.write(table_text)
