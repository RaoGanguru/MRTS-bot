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

# -------------------- MRTS list --------------------
mrts_set = set()
if not clauses_df.empty and "mrts" in clauses_df.columns:
    mrts_set |= set(clauses_df["mrts"].astype(str).unique())
if not tables_df.empty and "mrts" in tables_df.columns:
    mrts_set |= set(tables_df["mrts"].astype(str).unique())

all_mrts = sorted([m for m in mrts_set if str(m).strip()])

# -------------------- UI --------------------
selected_mrts = st.selectbox("Select MRTS", ["All MRTS"] + all_mrts)
search_text = st.text_input(
    "Search (examples: asphalt thickness tolerance, Table 9.4.2.3, EME thickness, bitumen temperature)"
)

# ✅ Main behaviour toggle
require_all_keywords = st.checkbox("Require ALL subject keywords (recommended)", value=True)

if not search_text.strip():
    st.info("Type a keyword to search. Example: asphalt thickness tolerance, Table 9.4.2.3, EME thickness.")
    st.stop()

# -------------------- Helpers --------------------
STOP_WORDS = set([
    "the","and","for","with","from","into","that","this","shall","must","may","than","then","any",
    "to","of","in","on","at","be","is","are","was","were","as"
])

# Words to ignore (question words)
QUESTION_WORDS = set([
    "what","how","when","where","why","who","which","give","tell","show","explain","provide",
    "please","kindly","can","could","would","should"
])

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

GENERIC_TITLE_PENALTY = ["general", "geometrics", "submission", "test results", "time for submission"]

def normalize_words(q: str):
    parts = re.findall(r"[a-zA-Z0-9\.]+", q.lower())
    words = [p for p in parts if len(p) > 2 and p not in STOP_WORDS]
    # de-duplicate preserve order
    seen = set()
    out = []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out

def subject_words(words):
    return [w for w in words if w not in QUESTION_WORDS]

def first_anchor_word(words_list):
    return words_list[0] if words_list else ""

def is_noise_title(title: str) -> bool:
    t = str(title).lower()
    return any(p in t for p in NOISE_TITLE_PATTERNS)

def generic_penalty(title: str) -> int:
    t = str(title).lower()
    return 6 if any(g in t for g in GENERIC_TITLE_PENALTY) else 0

def contains_any(text: str, words_):
    t = text.lower()
    return any(w in t for w in words_)

# -------------------- Query parsing --------------------
words = normalize_words(search_text)
core_words = subject_words(words)

# fallback if user typed only question words
if not core_words:
    core_words = words[:]

anchor = first_anchor_word(core_words)  # ✅ anchor = first subject word
qlower = search_text.lower()

# Special: if user wrote asphalt+thickness+tolerance, enforce those 3 strongly
force_triplet = (
    ("asphalt" in core_words) and
    ("thickness" in core_words) and
    (("tolerance" in core_words) or ("toler" in qlower))
)

# Phrase used only for scoring (not filtering)
phrase = " ".join(core_words) if len(core_words) >= 2 else ""

# Table intent hint
TABLE_INTENT_TERMS = ["table", "toler", "allowable", "limit", "min", "max", "thickness", "air", "void"]
table_intent = any(t in qlower for t in TABLE_INTENT_TERMS)

# -------------------- Scoring --------------------
def score_clause_row(row):
    score = 0
    cid   = str(row.get("clause_id","")).lower()
    title = str(row.get("title","")).lower()
    text  = str(row.get("text","")).lower()

    # Phrase boosts
    if phrase and phrase in title:
        score += 14
    if phrase and phrase in text:
        score += 10

    # Word boosts
    for w in core_words:
        if w in cid:
            score += 6
        if w in title:
            score += 5
        if w in text:
            score += 2

    score -= generic_penalty(title)
    return score

def score_table_row(row):
    score = 0
    table_id = str(row.get("table_id","")).lower()
    param    = str(row.get("parameter","")).lower()
    vtext    = str(row.get("value_text","")).lower()
    notes    = str(row.get("notes","")).lower()

    combined = f"{table_id} {param} {vtext} {notes}"

    if phrase and phrase in combined:
        score += 14

    for w in core_words:
        if w in table_id:
            score += 7
        if w in param:
            score += 6
        if w in vtext:
            score += 4
        if w in notes:
            score += 1

    if table_intent:
        score += 4

    return score

# -------------------- Filter + Rank --------------------
def filter_and_rank_tables(df, query_tokens, require_all=True):
    import pandas as pd

    if df is None or len(df) == 0:
        return df

    out = df.copy()

    needed_cols = ["mrts", "table_id", "caption", "parameter", "value", "units", "notes", "table_text", "pages", "page"]
    for c in needed_cols:
        if c not in out.columns:
            out[c] = ""

    for c in needed_cols:
        out[c] = out[c].fillna("").astype(str)

    out["_search_blob"] = (
        out["mrts"] + " " +
        out["table_id"] + " " +
        out["caption"] + " " +
        out["parameter"] + " " +
        out["value"] + " " +
        out["units"] + " " +
        out["notes"] + " " +
        out["table_text"] + " " +
        out["pages"] + " " +
        out["page"]
    ).str.lower()

    if not query_tokens:
        out["_score"] = 0
        return out

    def score_row(text):
        return sum(1 for t in query_tokens if t in text)

    out["_score"] = out["_search_blob"].apply(score_row)

    if require_all:
        out = out[out["_search_blob"].apply(lambda t: all(q in t for q in query_tokens))]
    else:
        out = out[out["_score"] > 0]

    return out.sort_values("_score", ascending=False)

# -------------------- UI Output --------------------
tab1, tab2 = st.tabs(["🟦 Clauses (ranked)", "🟩 Tables / OCR (ranked)"])

# Helpful banner for table-type questions
if table_intent and require_all_keywords:
    if tables_f.empty:
        st.warning("This looks like a table-type question (tolerance/thickness). No table match found. Your tables CSV likely needs OCR text in value_text.")
    else:
        st.success(f"Table matches found: {len(tables_f)} (anchor + AND match).")

with tab1:
    if clauses_f.empty:
        st.info("No clause results found with current rules. Tip: select the correct MRTS, or uncheck 'Require ALL subject keywords'.")
    else:
        MAX_RESULTS = 10
        st.caption(f"Showing top {min(len(clauses_f), MAX_RESULTS)} clause results.")
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
        st.info("No table/OCR results found. Tip: put OCR table text into 'value_text' column so it becomes searchable.")
    else:
        MAX_RESULTS = 10
        st.caption(f"Showing top {min(len(tables_f), MAX_RESULTS)} table/OCR results.")
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
