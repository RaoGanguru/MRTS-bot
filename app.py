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
search_text = st.text_input("Search (e.g. EME thickness, air voids, Table 8.2)")

def filter_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()

    if selected_mrts != "All MRTS" and "mrts" in out.columns:
        out = out[out["mrts"].astype(str) == selected_mrts]

    if search_text.strip():
        words = [w.lower() for w in search_text.split() if len(w) > 2]
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
        st.info("No clause results found.")
    else:
        # Required columns: mrts, clause_id, title, page_start, page_end, text
        for _, r in clauses_f.iterrows():
            clause_id = r.get("clause_id", "")
            title = r.get("title", "Clause")
            header = f"{clause_id} – {title}".strip(" –")
            with st.expander(header):
                st.markdown(r.get("text", ""))
                st.caption(f"MRTS {r.get('mrts','')} | Pages {r.get('page_start','')}–{r.get('page_end','')}")

with tab2:
    if tables_f.empty:
        st.info("No table/OCR results found.")
    else:
        # Recommended columns: mrts, clause, table_id, parameter, min, max, units, value_text, page, notes, source
        display_cols = [c for c in ["mrts","clause","table_id","parameter","min","max","units","page","notes"] if c in tables_f.columns]
        st.dataframe(tables_f[display_cols], use_container_width=True)
        st.caption("OCR extracted tables – verify against official MRTS.")

