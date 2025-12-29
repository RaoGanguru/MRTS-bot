import streamlit as st
import pandas as pd

# Page setup
st.set_page_config(
    page_title="TMR MRTS Asphalt Reference",
    layout="centered"
)

st.title("TMR MRTS Asphalt Reference")
st.subheader("Minimum Thickness for EME Asphalt")

# --- Short Answer ---
st.markdown("### 🔹 Answer")
st.write(
    "Under **TMR MRTS 32 (March 2024)**, the **nominated thickness** for "
    "**EME asphalt** must be within the range specified in Table 8.2. "
    "EME asphalt is **not a wearing course**."
)

# --- Table Data (Authoritative) ---
data = {
    "Asphalt Type": [
        "EME Asphalt"
    ],
    "Layer Function": [
        "Structural asphalt layer (not wearing course)"
    ],
    "Minimum Nominated Thickness (mm)": [
        70
    ],
    "Maximum Nominated Thickness (mm)": [
        130
    ],
    "Reference": [
        "MRTS 32 – March 2024, Table 8.2"
    ]
}

df = pd.DataFrame(data)

# --- Display Table ---
st.markdown("### 🔹 Nominated Thickness – EME Asphalt (TMR QLD)")
st.dataframe(df, use_container_width=True)

# --- Notes ---
st.markdown("### 🔹 Notes")
st.markdown(
    """
- EME asphalt is used as a **structural layer** and is **not a wearing course**.
- Thickness values shown are **nominated thicknesses**, not construction tolerances.
- Project-specific specifications may **override MRTS requirements**.
- Thickness tolerances are specified separately within **MRTS 32**.
"""
)

# --- Reference ---
st.markdown("### 🔹 Reference")
st.markdown(
    """
- **Transport and Main Roads (QLD)**  
- **MRTS 32 – Asphalt**  
- **March 2024**  
- **Table 8.2 – Nominated Thickness**
"""
)

# --- Deep Reading Option ---
with st.expander("📄 View full MRTS section (Table 8.2)"):
    st.write(
        "This section will provide access to the full MRTS 32 clause and "
        "Table 8.2 showing nominated thickness requirements for EME asphalt."
)





