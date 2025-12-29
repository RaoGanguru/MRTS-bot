
import streamlit as st
import pandas as pd

st.set_page_config(page_title="TMR MRTS 32 Asphalt Reference", layout="centered")

st.title("TMR MRTS 32 Asphalt Reference (QLD)")
st.caption("Structured reference tool — presents MRTS values with notes and references. No compliance decisions.")

# Load data
DATA_FILE = "asphalt_mrts32.csv"

try:
    df = pd.read_csv(DATA_FILE)
except Exception as e:
    st.error(f"Could not load data file: {DATA_FILE}")
    st.code(str(e))
    st.stop()

# Basic cleanup for display
df = df.fillna("")

# Filters (mobile-friendly)
topic_options = ["All"] + sorted([t for t in df["topic"].unique() if t])
material_options = ["All"] + sorted([m for m in df["material"].unique() if m])

topic = st.selectbox("Topic", topic_options, index=0)
material = st.selectbox("Material / Mix", material_options, index=0)

filtered = df.copy()
if topic != "All":
    filtered = filtered[filtered["topic"] == topic]
if material != "All":
    filtered = filtered[filtered["material"] == material]

st.markdown("### Results")
st.dataframe(filtered, use_container_width=True)

# Friendly “Answer-style” view for common items
st.markdown("### Quick view")
for _, row in filtered.iterrows():
    st.markdown(f"**{row['topic']} — {row['material']} — {row['property']} ({row['layer_or_class']})**")

    # Thickness range
    if row["value_min"] != "" or row["value_max"] != "":
        st.write(f"- Range: **{row['value_min']}–{row['value_max']} {row['units']}**")

    # Tolerances
    if row["tolerance_avg"] != "":
        st.write(f"- Tolerance (average): **± {row['tolerance_avg']} {row['units']}**")
    if row["tolerance_individual"] != "":
        st.write(f"- Tolerance (individual): **± {row['tolerance_individual']} {row['units']}**")

    # Notes + Reference
    if row["notes"] != "":
        st.write(f"- Notes: {row['notes']}")
    ref_bits = [row["reference_doc"], row["reference_date"], row["reference_table"], row["reference_clause"]]
    ref = ", ".join([b for b in ref_bits if b])
    if ref:
        st.write(f"- Reference: {ref}")

    st.divider()


