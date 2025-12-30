import streamlit as st
import pandas as pd
import os

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

# MRTS list
mrts_set = set()
if not clauses_df.empty and "mrts" in clauses_df.columns:
    mrts_set |= set(clauses_df["mrts"].astype(str).unique())
if not tables_df.empty and "mrts" in tables_df.columns:
    mrts_set |= set(tables_df["mrts"].astype(str).unique())
all_mrts = sorted([m for m in mrts_set if m.strip()])

selected_mrts = st.selectbox("Select MRTS", ["All MRTS"] + all_mrts)
search_text = st.text_input("Search (try: pavement, stabilisation, compaction, moisture, sampling, bitumen)")

# ✅ UX FIX: don’t dump all clauses when search is empty
if not search_text.strip():
    st.info("Type a keyword to search. Example: pavement, stabilisation, compaction, moisture, sampling, bitumen.")
    st.stop()

def filter_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()

    if selected_mrts != "All MRTS" and "mrts" in out.columns:
        out = out[out["mrts"].astype(str) == selected_mrts]

    words = [w.lower() for w in search_text.split() if len(w) > 2]

    # keyword match across whole row
    out = out[out.apply(
        lambda r: any(w in " ".join(r.astype(str)).lower() for w in words),
        axis=1
    )]
    return out

clauses_f = filter_df(clauses_df)
tables_f  = filter_df(tables_df)

tab1, tab2 = st.tabs(["🟦 Clauses", "🟩 Tables / OCR"])

with tab1:
    if clauses_f.empty:
        st.info("No clause results found. Try different keywords.")
    else:
        MAX_RESULTS = 25
        st.caption(f"Showing top {min(len(clauses_f), MAX_RESULTS)} results (limit {MAX_RESULTS}).")
        for _, r in clauses_f.head(MAX_RESULTS).iterrows():
            clause_id = r.get("clause_id", "")
            title = r.get("title", "Clause")
            header = f"{clause_id} – {title}".strip(" –")

            text = r.get("text", "")
            snippet = text[:350] + ("..." if len(text) > 350 else "")

            with st.expander(header):
                st.write(snippet)
                st.caption(f"MRTS {r.get('mrts','')} | Pages {r.get('page_start','')}–{r.get('page_end','')}")
                st.markdown("---")
                st.markdown(text)

with tab2:
    # OCR tab is useful only if value_text contains real OCR text
    if tables_f.empty:
        st.info("No table/OCR results found. (Tip: OCR text must be in the 'value_text' column.)")
    else:
        MAX_RESULTS = 25
        st.caption(f"Showing top {min(len(tables_f), MAX_RESULTS)} OCR results (limit {MAX_RESULTS}).")

        # Show OCR cards (better than empty dataframe)
        for _, r in tables_f.head(MAX_RESULTS).iterrows():
            mrts = r.get("mrts","")
            page = r.get("page","")
            value_text = str(r.get("value_text","")).strip()
            notes = str(r.get("notes","")).strip()

            if not value_text and not notes:
                continue

            title = f"{mrts} | Page {page}".strip()
            with st.expander(title):
                if notes:
                    st.caption(notes)
                st.text(value_text if value_text else "(No OCR text in value_text)")
                st.caption("OCR extracted – verify against official MRTS.")


