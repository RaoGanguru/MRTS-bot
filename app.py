import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="MRTS Reference Viewer", layout="wide")
st.title("MRTS Reference Viewer (QLD)")
st.caption("Read-only MRTS reference. Clauses + OCR tables. Verify against official MRTS.")

DATA_FOLDER = "mrts_data"

# ---------- Load all CSVs ----------
def load_csvs(suffix):
    frames = []
    for f in os.listdir(DATA_FOLDER):
        if f.lower().endswith(suffix):
            try:
                df = pd.read_csv(os.path.join(DATA_FOLDER, f)).fillna("")
                frames.append(df)
            except:
                pass
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

clauses_df = load_csvs("_structured_clauses.csv")
tables_df  = load_csvs("_tables_ocr.csv")

# ---------- MRTS selector ----------
all_mrts = sorted(
    set(clauses_df.get("mrts", [])).union(set(tables_df.get("mrts", [])))
)

selected_mrts = st.selectbox(
    "Select MRTS",
    ["All MRTS"] + all_mrts
)

search_text = st.text_input("Search (e.g. EME thickness, air voids, Table 8.2)")

def filter_df(df):
    if df.empty:
        return df
    temp = df.copy()
    if selected_mrts != "All MRTS":
        temp = temp[temp["mrts"] == selected_mrts]
    if search_text.strip():
        words = [w.lower() for w in search_text.split() if len(w) > 2]
        temp = temp[temp.apply(
            lambda r: any(w in " ".join(r.astype(str)).lower() for w in words),
            axis=1
        )]
    return temp

clauses_f = filter_df(clauses_df)
tables_f  = filter_df(tables_df)

# ---------- UI Tabs ----------
tab1, tab2
