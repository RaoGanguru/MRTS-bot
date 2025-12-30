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
search_text = st.text_input("Search (examples: thickness tolerance, Table 9.4.2.3, allowable tolerance, EME thickness)")

# Strictness slider = how many words must match (95–100% = almost all words)
strict_pct = st.slider("Search strictness (higher = more exact matches)", 60, 100, 95)

if not search_text.strip():
    st.info("Type a keyword to search. Example: thickness tolerance, Table 9.4.2.3, EME thickness.")
    st.stop()

# -------------------- Helpers --------------------
STOP_WORDS = set([
    "the","and","for","with","from","into","that","this","shall","must","may","than","then","any",
    "to","of","in","on","at","be","is","are","was","were","as"
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
    # de-duplicate while preserving order
    seen = set()
    out = []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out

def is_noise_title(title: str) -> bool:
    t = str(title).lower()
    return any(p in t for p in NOISE_TITLE_PATTERNS)

def generic_penalty(title: str) -> int:
    t = str(title).lower()
    return 6 if any(g in t for g in GENERIC_TITLE_PENALTY) else 0

words = normalize_words(search_text)
phrase = " ".join(words) if len(words) >= 2 else ""

def required_hits(words, strict_pct):
    """
    Convert strictness % into required word hits.
    100% = all words
    95% = almost all words
    """
    if not words:
        return 0
    req = int((strict_pct / 100) * len(words))
    # Make sure it isn't too low when strictness is high
    if strict_pct >= 95:
        req = max(req, len(words) - 0)  # basically all words
    elif strict_pct >= 85:
        req = max(req, len(words) - 1)
    else:
        req = max(req, 1)
    return min(req, len(words))

REQ_HITS = required_hits(words, strict_pct)

def count_hits(text: str, words):
    t = text.lower()
    return sum(1 for w in words if w in t)

def passes_strictness(combined_text: str) -> bool:
    return count_hits(combined_text, words) >= REQ_HITS

# Detect table-intent queries (because tolerances often in tables)
TABLE_INTENT_TERMS = ["table", "toler", "allowable", "limit", "min", "max", "thickness", "air", "void"]
qlower = search_text.lower()
table_intent = any(t in qlower for t in TABLE_INTENT_TERMS)

# -------------------- Scoring --------------------
def score_clause_row(row):
    score = 0
    cid   = str(row.get("clause_id","")).lower()
    title = str(row.get("title","")).lower()
    text  = str(row.get("text","")).lower()

    # Phrase boosts
    if phrase and phrase in title:
        score += 12
    if phrase and phrase in text:
        score += 8

    # Word boosts
    for w in words:
        if w in cid:
            score += 6
        if w in title:
            score += 4
        if w in text:
            score += 1

    score -= generic_penalty(title)
    return score

def score_table_row(row):
    score = 0
    table_id = str(row.get("table_id","")).lower()
    param    = str(row.get("parameter","")).lower()
    vtext    = str(row.get("value_text","")).lower()
    notes    = str(row.get("notes","")).lower()

    if phrase and (phrase in table_id or phrase in param or phrase in vtext):
        score += 12

    for w in words:
        if w in table_id:
            score += 6
        if w in param:
            score += 5
        if w in vtext:
            score += 3
        if w in notes:
            score += 1

    # Table intent queries should prefer tables
    if table_intent:
        score += 3

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

    # If asphalt query, require asphalt present
    if "asphalt" in qlower and "title" in out.columns and "text" in out.columns:
        out = out[
            out["title"].str.contains("asphalt", case=False, na=False) |
            out["text"].str.contains("asphalt", case=False, na=False)
        ]

    # If tolerance query, require tolerance
    if "toler" in qlower and "text" in out.columns:
        out = out[out["text"].str.contains(r"toler", case=False, na=False)]

    # Strictness filter (95–100% = must match almost all words)
    combined = (
        out.get("clause_id","").astype(str) + " " +
        out.get("title","").astype(str) + " " +
        out.get("text","").astype(str)
    )
    out = out[combined.apply(passes_strictness)]

    out["score"] = out.apply(lambda r: score_clause_row(r), axis=1)
    out = out[out["score"] > 0].sort_values("score", ascending=False)
    return out

def filter_and_rank_tables(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()

    if selected_mrts != "All MRTS" and "mrts" in out.columns:
        out = out[out["mrts"].astype(str) == selected_mrts]

    # If asphalt query, require asphalt in any table field
    if "asphalt" in qlower:
        combined_a = (
            out.get("table_id","").astype(str) + " " +
            out.get("parameter","").astype(str) + " " +
            out.get("value_text","").astype(str) + " " +
            out.get("notes","").astype(str)
        )
        out = out[combined_a.str.contains("asphalt", case=False, na=False)]

    combined = (
        out.get("table_id","").astype(str) + " " +
        out.get("parameter","").astype(str) + " " +
        out.get("value_text","").astype(str) + " " +
        out.get("notes","").astype(str)
    )
    out = out[combined.apply(passes_strictness)]

    out["score"] = out.apply(lambda r: score_table_row(r), axis=1)
    out = out[out["score"] > 0].sort_values("score", ascending=False)
    return out

clauses_f = filter_and_rank_clauses(clauses_df)
tables_f  = filter_and_rank_tables(tables_df)

# -------------------- UI Output --------------------
tab1, tab2 = st.tabs(["🟦 Clauses (ranked)", "🟩 Tables / OCR (ranked)"])

# Banner to push table-first thinking when relevant
if table_intent:
    if not tables_f.empty:
        st.success(f"Tables likely contain your answer. Found {len(tables_f)} matching table/OCR rows.")
    else:
        st.warning("This looks like a tables-type question (tolerances/thickness). No matching table/OCR rows found — your tables CSV may need more OCR text in value_text.")

with tab2:
    if tables_f.empty:
        st.info("No table/OCR results found. Tip: put OCR text into the 'value_text' column so it can be searched.")
    else:
        MAX_RESULTS = 15
        st.caption(f"Showing top {min(len(tables_f), MAX_RESULTS)} tables/OCR results (strictness {strict_pct}%).")
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
                # If you later add structured columns, show them if present
                for col in ["min_value","max_value","unit","tolerance_avg","tolerance_individual"]:
                    if col in r and str(r.get(col,"")).strip():
                        st.write(f"**{col}:** {r.get(col)}")
                if notes:
                    st.caption(notes)
                st.text(vtext if vtext else "(No OCR text in value_text)")
                st.caption("OCR extracted – verify against official MRTS.")

with tab1:
    if clauses_f.empty:
        st.info("No clause results found (strict). Lower strictness slider to 80–90% if needed.")
    else:
        MAX_RESULTS = 15
        st.caption(f"Showing top {min(len(clauses_f), MAX_RESULTS)} clause results (strictness {strict_pct}%).")
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
