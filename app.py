import streamlit as st
import pandas as pd
import os
import re

st.set_page_config(page_title="MRTS Reference Viewer", layout="wide")
st.title("MRTS Reference Viewer (QLD)")
st.caption("Read-only MRTS reference. Clauses + OCR tables. Verify against official MRTS.")

DATA_FOLDER = "mrts_data"

# -------------------- Safety checks --------------------
if not os.path.exists(DATA_FOLDER):
    st.error("Folder not found: mrts_data. Create it in GitHub and upload CSVs into it.")
    st.stop()

# -------------------- Load CSVs --------------------
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

# -------------------- Sidebar debug (optional) --------------------
# Uncomment if you want to keep debug:
# st.sidebar.header("Debug")
# st.sidebar.write("Files:", os.listdir(DATA_FOLDER))
# st.sidebar.write("Clauses rows:", 0 if clauses_df.empty else len(clauses_df))
# st.sidebar.write("Tables/OCR rows:", 0 if tables_df.empty else len(tables_df))

# -------------------- MRTS list --------------------
mrts_set = set()
if not clauses_df.empty and "mrts" in clauses_df.columns:
    mrts_set |= set(clauses_df["mrts"].astype(str).unique())
if not tables_df.empty and "mrts" in tables_df.columns:
    mrts_set |= set(tables_df["mrts"].astype(str).unique())
all_mrts = sorted([m for m in mrts_set if m.strip()])

selected_mrts = st.selectbox("Select MRTS", ["All MRTS"] + all_mrts)
search_text = st.text_input("Search (try: tolerance compaction, stabilised pavement, moisture, sampling, bitumen)")

# ✅ Don’t dump everything
if not search_text.strip():
    st.info("Type a keyword to search. Example: tolerance compaction, stabilised pavement, moisture, sampling, bitumen.")
    st.stop()

# -------------------- Helpers --------------------
STOP_WORDS = set(["the", "and", "for", "with", "from", "into", "that", "this", "shall", "must", "may"])
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

def normalize_words(q: str):
    # keep words and numbers, remove punctuation
    parts = re.findall(r"[a-zA-Z0-9\.]+", q.lower())
    words = [p for p in parts if len(p) > 2 and p not in STOP_WORDS]
    return words

def is_noise_title(title: str) -> bool:
    t = str(title).lower()
    return any(p in t for p in NOISE_TITLE_PATTERNS)

def score_clause_row(row, words, phrase):
    """
    Weighted scoring:
    - clause_id match: +6
    - title match: +4
    - text match: +1
    - phrase match in title/text: +8
    """
    score = 0
    cid   = str(row.get("clause_id","")).lower()
    title = str(row.get("title","")).lower()
    text  = str(row.get("text","")).lower()

    if phrase and phrase in title:
        score += 8
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
    """
    Tables scoring: prioritize table_id/parameter/value_text.
    """
    score = 0
    table_id = str(row.get("table_id","")).lower()
    param    = str(row.get("parameter","")).lower()
    vtext    = str(row.get("value_text","")).lower()
    notes    = str(row.get("notes","")).lower()

    if phrase and (phrase in table_id or phrase in param or phrase in vtext):
        score += 8

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

# -------------------- Filtering + ranking --------------------
words = normalize_words(search_text)
phrase = " ".join(words) if len(words) >= 2 else ""

def filter_and_rank_clauses(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()

    # MRTS filter
    if selected_mrts != "All MRTS" and "mrts" in out.columns:
        out = out[out["mrts"].astype(str) == selected_mrts]

    # Remove noisy sections (big improvement)
    if "title" in out.columns:
        out = out[~out["title"].apply(is_noise_title)]

    # Require tolerance-related content if user asked tolerance
    qlower = search_text.lower()
    if "toler" in qlower and "text" in out.columns:
        out = out[out["text"].str.contains(r"toler", case=False, na=False)]

    # Score
    out["score"] = out.apply(lambda r: score_clause_row(r, words, phrase), axis=1)
    out = out[out["score"] > 0]
    out = out.sort_values("score", ascending=False)
    return out

def filter_and_rank_tables(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()

    if selected_mrts != "All MRTS" and "mrts" in out.columns:
        out = out[out["mrts"].astype(str) == selected_mrts]

    # Score
    out["score"] = out.apply(lambda r: score_table_row(r, words, phrase), axis=1)
    out = out[out["score"] > 0]
    out = out.sort_values("score", ascending=False)
    return out

clauses_f = filter_and_rank_clauses(clauses_df)
tables_f  = filter_and_rank_tables(tables_df)

# -------------------- UI --------------------
tab1, tab2 = st.tabs(["🟦 Clauses (ranked)", "🟩 Tables / OCR (ranked)"])

with tab1:
    if clauses_f.empty:
        st.info("No clause results found. Try different keywords (e.g. 'tolerance compaction', 'stabilisation', 'moisture').")
    else:
        MAX_RESULTS = 15
        st.caption(f"Showing top {min(len(clauses_f), MAX_RESULTS)} results (ranked).")

        for _, r in clauses_f.head(MAX_RESULTS).iterrows():
            clause_id = r.get("clause_id", "")
            title = r.get("title", "Clause")
            score = r.get("score", 0)

            header = f"[{int(score)}] {clause_id} – {title}".strip(" –")

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
            score = r.get("score", 0)
            mrts = r.get("mrts","")
            page = r.get("page","")
            clause = r.get("clause","")
            table_id = r.get("table_id","")
            param = r.get("parameter","")
            vtext = str(r.get("value_text","")).strip()
            notes = str(r.get("notes","")).strip()

            title = f"[{int(score)}] {mrts} | Page {page} | {table_id}".strip()

            with st.expander(title):
                if clause:
                    st.caption(f"Clause: {clause}")
                if param:
                    st.write(f"**Parameter:** {param}")
                if notes:
                    st.caption(notes)
                st.text(vtext if vtext else "(No OCR text in value_text)")
                st.caption("OCR extracted – verify against official MRTS.")



