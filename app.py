
import streamlit as st
import pandas as pd
import os

# -----------------------------
# Page setup
# -----------------------------
st.set_page_config(
    page_title="MRTS Reference Viewer",
    layout="wide"
)

st.title("MRTS Reference Viewer (QLD)")
st.caption(
    "Structured MRTS reference tool. "
    "Displays requirements, procedures, inspections, and records exactly as stored. "
    "No compliance decisions."
)

# -----------------------------
# Data folder
# -----------------------------
DATA_FOLDER = "mrts_data"

if not os.path.exists(DATA_FOLDER):
    st.warning("No MRTS data folder found. Please upload CSV files to /mrts_data.")
    st.stop()

# -----------------------------
# Load CSV files
# -----------------------------
csv_files = [f for f in os.listdir(DATA_FOLDER) if f.lower().endswith(".csv")]

if not csv_files:
    st.warning("No CSV files found in /mrts_data yet.")
    st.stop()

# Friendly names for selector
mrtx_map = {f: f.replace("_", " ").replace(".csv", "") for f in csv_files}

# -----------------------------
# MRTS selector
# -----------------------------
selected_file = st.selectbox(
    "Select MRTS document",
    options=csv_files,
    format_func=lambda x: mrtx_map[x]
)

file_path = os.path.join(DATA_FOLDER, selected_file)

try:
    df = pd.read_csv(file_path)
except Exception as e:
    st.error("Unable to read the selected CSV file.")
    st.code(str(e))
    st.stop()

df = df.fillna("")

# -----------------------------
# Search
# -----------------------------
search_text = st.text_input("Search keyword (e.g. thickness, air voids, testing)")

if search_text:
    mask = df.apply(
        lambda row: row.astype(str).str.contains(search_text, case=False).any(),
        axis=1
    )
    filtered_df = df[mask]
else:
    filtered_df = df

st.markdown("### Results")

if filtered_df.empty:
    st.info("No matching records found.")
    st.stop()

# -----------------------------
# Display results
# -----------------------------
for idx, row in filtered_df.iterrows():
    with st.expander(f"{row.get('Description', 'MRTS Entry')}"):
        if "Clause" in row:
            st.markdown(f"**Clause:** {row['Clause']}")
        if "Responsibility" in row:
            st.markdown(f"**Responsibility:** {row['Responsibility']}")
        if "Records" in row:
            st.markdown(f"**Records:** {row['Records']}")
        if "Inspection Method" in row:
            st.markdown(f"**Inspection Method:** {row['Inspection Method']}")

        # Show all remaining fields safely
        st.markdown("---")
        for col in df.columns:
            if col not in [
                "Description",
                "Clause",
                "Responsibility",
                "Records",
                "Inspection Method"
            ]:
                value = row[col]
                if str(value).strip():
                    st.markdown(f"**{col}:** {value}")

# -----------------------------
# Footer
# -----------------------------
st.caption(
    "Note: This tool presents MRTS content as stored in CSV files. "
    "Always verify against the official MRTS documents."
)
# -----------------------------
# MRTS selector (add ALL)
# -----------------------------
csv_files = [f for f in os.listdir(DATA_FOLDER) if f.lower().endswith(".csv")]
csv_files = sorted(csv_files)

mrtx_map = {f: f.replace("_", " ").replace(".csv", "") for f in csv_files}
options = ["ALL_MRTS"] + csv_files

selected_file = st.selectbox(
    "Select MRTS document",
    options=options,
    format_func=lambda x: "All MRTS (search everything)" if x == "ALL_MRTS" else mrtx_map[x]
)

search_text = st.text_input("Search (try: EME thickness, air voids, Table 8.2)")

def load_one(path: str) -> pd.DataFrame:
    df1 = pd.read_csv(path).fillna("")
    df1["_source_file"] = os.path.basename(path)
    return df1

# -----------------------------
# Load data (one or all)
# -----------------------------
if selected_file == "ALL_MRTS":
    all_frames = []
    for f in csv_files:
        try:
            all_frames.append(load_one(os.path.join(DATA_FOLDER, f)))
        except:
            pass
    if not all_frames:
        st.warning("Could not load any CSV files from mrts_data.")
        st.stop()
    df = pd.concat(all_frames, ignore_index=True)
else:
    file_path = os.path.join(DATA_FOLDER, selected_file)
    df = load_one(file_path)

# -----------------------------
# Smarter search: split into keywords
# -----------------------------
df = df.fillna("")
filtered_df = df

if search_text.strip():
    words = [w.strip().lower() for w in search_text.replace("?", "").split() if len(w.strip()) >= 3]

    def row_matches(row) -> bool:
        text = " ".join(row.astype(str).tolist()).lower()
        return any(w in text for w in words)

    mask = df.apply(row_matches, axis=1)
    filtered_df = df[mask]

st.markdown("### Results")

if filtered_df.empty:
    st.info("No matching records found. Try keywords like: EME, thickness, air voids, Table 8.2.")
    st.stop()

# Show source file first if searching ALL
show_cols = list(filtered_df.columns)
if "_source_file" in show_cols:
    st.caption("Tip: results show which MRTS file they came from.")