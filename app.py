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
all_mrts = sorted([m for m in mrts_set if m.strip()])

# -------------------- UI --------------------
selected_mrts = st.selectbox("Select MRTS", ["All MRTS"] + all_mrts)
search_text = st.text_input("Search (examples: asphalt thickness tolerance, Table 9.4.2.3, EME thickness, bitumen temperature)")

# ✅ NEW: strict AND matching toggle
require_all_keywords = st.checkbox("Require ALL subject keywords (recommended)", value=True)

if not search_text.strip():
    st.info("Type a keyword to search. Example: asphalt thickness tolerance, Table 9.4.2.3, EME thickness.")
    st.stop()

# -------------------- Helpers --------------------
STOP_WORDS = set([
    "the","and","for","with","from","into","that","this","shall","must","may","than","then","any",
    "to","of","in","on","at","be","is","are","was","were","as"
])

# Question words we want to ignore
QUESTION_WORDS = set([
    "what","how","when","where","why","who","which","give","tell","show","explain","provide",
    "minimum","maximum"  # optional: keep if you want these to matter; remove if too strict
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
    """Remove question words; keep only subject terms."""
    return [w for w in words if w not in QUESTION_WORDS]

def is_noise_title(title: str) -> bool:
    t = str(title).lower()
    return any(p in t for p in NOISE_TITLE_PATTERNS)

def generic_penalty(title: str) -> int:
    t = str(title).lower()
    return 6 if any(g in t for g in GENERIC_TITLE_PENALTY) else 0

def contains_all(text: str, must_words):
    t = text.lower()
    return all(w in t for w in must_words)

def contains_any(text: str, words_):
    t = text.lower()
    return any(w in t for w in words_)

words = normalize_words(search_text)
core_words = subject_words(words)  # ✅ subject terms only
phrase = " ".join(core_words) if len(core_words) >= 2 else ""

qlower = search_text.lower()

# If user typed only question words, fall back to original words
if not core_words:
    core_words = words[:]

# Special: if user wrote asphalt+thickness+tolerance, enforce ALL 3
force_triplet = ("asphalt" in core_words and "thickness" in core_words and ("tolerance" in core_words or "toler" in qlower))
if force_triplet:
    # normalise "tolerance" requirement even if user typed "tolerances"
    must_have = ["asphalt", "thickness", "toler"]
else:
    must_have = core_words

# Table-intent hint
TABLE_INTENT_TERMS = ["table", "toler", "allowable", "limit", "min", "max", "thickness", "air", "void"]
table_intent = any(t in qlower for t in TABLE_INTENT_TERMS)

# -------------------- Scoring --------------------
def score_clause_row(row):
    score = 0
    cid   = str(row.get("clause_id","")).lower()
    title = str(row.get("title","")).lower()
    text  = str(row.get("text","")).lower()

    # Phrase boosts (subject phrase)
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

    # Phrase boost
    if phrase and phrase in combined:
        score += 14

    # Word boosts
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

# -------------------- Filter + rank --------------------
def filter_and_rank_clauses(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()

    if selected_mrts != "All MRTS" and "mrts" in out.columns:
        out = out[out["mrts"].astype(str) == selected_mrts]

    if "title" in out.columns:
        out = out[~out["title"].apply(is_noise_title)]

    # If asphalt in query, require asphalt in title/text (prevents cross-topic junk)
    if "asphalt" in qlower and "title" in out.columns and "text" in out.columns:
        out = out[
            out["title"].str.contains("asphalt", case=False, na=False) |
            out["text"].str.contains("asphalt", case=False, na=False)
        ]

    # ✅ NEW: AND matching on subject keywords
    combined = (
        out.get("clause_id","").astype(str) + " " +
        out.get("title","").astype(str) + " " +
        out.get("text","").astype(str)
    )

    if require_all_keywords:
        # must contain all required words (or toler-root)
        def ok(s):
            s = str(s).lower()
            if force_triplet:
                return ("asphalt" in s) and ("thickness" in s) and ("toler" in s)
            else:
                return contains_all(s, must_have)
        out = out[combined.apply(ok)]
    else:
        # fallback: at least one word must match
        out = out[combined.apply(lambda s: contains_any(str(s), core_words))]

    if out.empty:
        return out

    out["score"] = out.apply(lambda r: score_clause_row(r), axis=1)
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

    if require_all_keywords:
        def ok(s):
            s = str(s).lower()
            if force_triplet:
                return ("asphalt" in s) and ("thickness" in s) and ("toler" in s)
            else:
                return contains_all(s, must_have)
        out = out[combined.apply(ok)]
    else:
        out = out[combined.apply(lambda s: contains_any(str(s), core_words))]

    if out.empty:
        return out

    out["score"] = out.apply(lambda r: score_table_row(r), axis=1)
    out = out[out["score"] > 0].sort_values("score", ascending=False)
    return out

clauses_f = filter_and_rank_clauses(clauses_df)
tables_f  = filter_and_rank_tables(tables_df)

# -------------------- UI Output --------------------
tab1, tab2 = st.tabs(["🟦 Clauses (ranked)", "🟩 Tables / OCR (ranked)"])

# Helpful banner for tolerance/thickness queries
if table_intent and require_all_keywords:
    if tables_f.empty:
        st.warning("This looks like a table-type question (tolerance/thickness). No table match found. Your tables CSV probably needs OCR text in value_text.")
    else:
        st.success(f"Table matches found: {len(tables_f)} (AND-matched subject keywords).")

with tab1:
    if clauses_f.empty:
        st.info("No clause results found under current AND rules. Try selecting the exact MRTS or switch OFF 'Require ALL subject keywords'.")
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
        st.info("No table/OCR results found. Tip: put OCR table text into 'value_text' column so it can be searched.")
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

