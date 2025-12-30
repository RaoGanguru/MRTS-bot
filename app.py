import streamlit as st
import pandas as pd
import os
import re

st.set_page_config(page_title="MRTS Reference Viewer", layout="wide")
st.title("MRTS Reference Viewer (QLD)")
st.caption("Read-only MRTS reference. Clauses + OCR tables. Verify against official MRTS.")

DATA_FOLDER = "mrts_data"
if not os.path.exists(DATA_FOLDER):
    st.error("Folder not found: mrts_data. Create it in GitHub and upload CSVs into it.")
    st.stop()

def load_csvs(endswith: str) -> pd.DataFrame:
    frames = []
    for f in os.listdir(DATA_FOLDER):
        if f.lower().endswith(endswith.lower()):
            try:
                df = pd.read_csv(os.path.join(DATA_FOLDER, f)).fillna("")
                frames.append(df)
            except Exception as e:
                st.warning(f"Could not read {f}: {e}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

clauses_df = load_csvs("_structured_clauses.csv")
tables_df  = load_csvs("_tables_ocr.csv")

# Build MRTS list
mrts_set = set()
if not clauses_df.empty and "mrts" in clauses_df.columns:
    mrts_set |= set(clauses_df["mrts"].astype(str).unique())
if not tables_df.empty and "mrts" in tables_df.columns:
    mrts_set |= set(tables_df["mrts"].astype(str).unique())
all_mrts = sorted([m for m in mrts_set if m.strip()])

# UI controls
selected_mrts = st.selectbox("Select MRTS", ["All MRTS"] + all_mrts)
search_text = st.text_input("Search (try: thickness tolerance, compaction tolerance, stabilised layer, moisture, bitumen)")

# Do not dump everything
if not search_text.strip():
    st.info("Type a keyword to search. Example: thickness tolerance, stabilised layer tolerance, compaction, moisture, bitumen.")
    st.stop()

STOP_WORDS = set(["the", "and", "for", "with", "from", "into", "that", "this", "shall", "must", "may", "than", "then", "any"])
NOISE_TITLE_PATTERNS = [
    "introduction",
    "definition",
    "referenced document",
    "referenced documents",
    "standard test",
    "test method",
    "definitions",
    "hold points",
    "witness points",
    "milestones",
]

# Simple intent → suggested MRTS (based on your current loaded docs)
# (Heuristic only; user can override.)
SUGGEST = [
    (["asphalt", "seal", "bitumen", "sprayed", "binder"], ["MRTS30", "MRTS11", "MRTS10", "MRTS12"]),
    (["stabilised", "stabilised", "stabilisation", "lime", "cement"], ["MRTS07B", "MRTS07C"]),
    (["unbound", "granular", "subbase", "basecourse"], ["MRTS05"]),
]

def normalize_words(q: str):
    parts = re.findall(r"[a-zA-Z0-9\.]+", q.lower())
    words = [p for p in parts if len(p) > 2 and p not in STOP_WORDS]
    return words

def is_noise_title(title: str) -> bool:
    t = str(title).lower()
    return any(p in t for p in NOISE_TITLE_PATTERNS)

words = normalize_words(search_text)
phrase = " ".join(words) if len(words) >= 2 else ""

def suggested_mrts_from_query(q: str):
    ql = q.lower()
    candidates = []
    for keys, mrts_list in SUGGEST:
        if any(k in ql for k in keys):
            candidates.extend([m for m in mrts_list if m in all_mrts])
    # unique preserve order
    seen = set()
    out = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out

suggested = suggested_mrts_from_query(search_text)

# If user selected All MRTS, offer a smart narrowing
if selected_mrts == "All MRTS" and suggested:
    st.warning(f"Your search looks like it belongs to: {', '.join(suggested)}. "
               f"Tip: filtering will remove unrelated MRTS results.")
    # Optional one-click narrowing
    if st.button("Filter to suggested MRTS (recommended)"):
        # Set first suggestion as scope for this run (soft scope)
        selected_mrts = suggested[0]

def score_clause_row(row, words, phrase):
    score = 0
    cid   = str(row.get("clause_id","")).lower()
    title = str(row.get("title","")).lower()
    text  = str(row.get("text","")).lower()

    if phrase and phrase in title:
        score += 10
    if phrase and phrase in text:
        score += 8

    for w in words:
        if w in cid:
            score += 6
        if w in title:
            score += 4
        if w in text:
            score += 1
    return score

def score_table_row(row, words, phrase):
    score = 0
    table_id = str(row.get("table_id","")).lower()
    param    = str(row.get("parameter","")).lower()
    vtext    = str(row.get("value_text","")).lower()
    notes    = str(row.get("notes","")).lower()

    if phrase and (phrase in table_id or phrase in param or phrase in vtext):
        score += 10

    for w in words:
        if w in table_id:
            score += 6
        if w in param:
            score += 5
        if w in vtext:
            score += 2
        if w in notes:
            score += 1
    return score

def min_match_filter_row(row_text: str, words, min_hits=2):
    """Reduce noise: require at least N query words to appear in the row text."""
    t = row_text.lower()
    hits = sum(1 for w in words if w in t)
    return hits >= min_hits

def filter_and_rank_clauses(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()

    # Scope by MRTS
    if selected_mrts != "All MRTS" and "mrts" in out.columns:
        out = out[out["mrts"].astype(str) == selected_mrts]

    # Remove noise titles
    if "title" in out.columns:
        out = out[~out["title"].apply(is_noise_title)]

    # If tolerance query, force tolerance presence (big relevance boost)
    if "toler" in search_text.lower() and "text" in out.columns:
        out = out[out["text"].str.contains(r"toler", case=False, na=False)]

    # Require at least 2 keyword hits in combined fields to avoid 1-word matches
    if not out.empty:
        combined = (
            out.get("clause_id","").astype(str) + " " +
            out.get("title","").astype(str) + " " +
            out.get("text","").astype(str)
        )
        out = out[combined.apply(lambda s: min_match_filter_row(s, words, min_hits=2 if len(words) >= 3 else 1))]

    # Score + sort
    out["score"] = out.apply(lambda r: score_clause_row(r, words, phrase), axis=1)
    out = out[out["score"] > 0].sort_values("score", ascending=False)
    return out

def filter_and_rank_tables(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()

    if selected_mrts != "All MRTS" and "mrts" in out.columns:
        out = out[out["mrts"].astype(str) == selected_mrts]

    combined = (
        out.get("table_id","").astype(str) + " " +
        out.get("parameter","").astype(str) + " " +
        out.get("value_text","").astype(str) + " " +
        out.get("notes","").astype(str)
    )
    out = out[combined.apply(lambda s: min_match_filter_row(s, words, min_hits=2 if len(words) >= 3 else 1))]

    out["score"] = out.apply(lambda r: score_table_row(r, words, phrase), axis=1)
    out = out[out["score"] > 0].sort_values("score", ascending=False)
    return out

clauses_f = filter_and_rank_clauses(clauses_df)
tables_f  = filter_and_rank_tables(tables_df)

tab1, tab2 = st.tabs(["🟦 Clauses (ranked)", "🟩 Tables / OCR (ranked)"])

with tab1:
    if clauses_f.empty:
        st.info("No clause results found. Try different keywords or filter to a specific MRTS.")
    else:
        MAX_RESULTS = 15
        st.caption(f"Showing top {min(len(clauses_f), MAX_RESULTS)} results (ranked).")
        for _, r in clauses_f.head(MAX_RESULTS).iterrows():
            clause_id = r.get("clause_id", "")
            title = r.get("title", "Clause")
            score = int(r.get("score", 0))
            header = f"[{score}] {clause_id} – {title}".strip(" –")

            full_text = str(r.get("text", "")).strip()
            snippet = full_text[:450] + ("..." if len(full_text) > 450 else "")

            with st.expander(header):
                st.write(snippet)
                st.caption(f"MRTS {r.get('mrts','')} | Pages {r.get('page_start','')}–{r.get('page_end','')}")
                st.markdown("---")
                st.markdown(full_text)

with tab2:
    if tables_f.empty:
        st.info("No table/OCR results found. (Tip: OCR text must be in the 'value_text' column.)")
    else:
        MAX_RESULTS = 15
        st.caption(f"Showing top {min(len(tables_f), MAX_RESULTS)} OCR results (ranked).")
        for _, r in tables_f.head(MAX_RESULTS).iterrows():
            score = int(r.get("score", 0))
            mrts = r.get("mrts","")
            page = r.get("page","")
            table_id = r.get("table_id","")
            param = r.get("parameter","")
            vtext = str(r.get("value_text","")).strip()
            notes = str(r.get("notes","")).strip()

            title = f"[{score}] {mrts} | Page {page} | {table_id}".strip()
            with st.expander(title):
                if param:
                    st.write(f"**Parameter:** {param}")
                if notes:
                    st.caption(notes)
                st.text(vtext if vtext else "(No OCR text in value_text)")
                st.caption("OCR extracted – verify against official MRTS.")




