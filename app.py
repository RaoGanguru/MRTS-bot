import streamlit as st
import pymupdf as fitz

st.set_page_config(page_title="MRTS Bot – Multi‑PDF Test", layout="wide")
st.title("MRTS Bot – Multi‑PDF Test")

uploaded_files = st.file_uploader("Upload one or more PDFs", type=["pdf"], accept_multiple_files=True)

if not uploaded_files:
    st.info("Upload PDFs to extract and preview their content.")
    st.stop()

for uf in uploaded_files:
    st.header(f"File: {uf.name}")
    try:
        doc = fitz.open(stream=uf.read(), filetype="pdf")
    except Exception as e:
        st.error(f"Could not open {uf.name}: {e}")
        continue

    st.write({"pages": doc.page_count})
    page = doc[0]

    # Text extraction
    text = page.get_text()
    st.text_area(f"Text from {uf.name} – page 1", text, height=240)

    # Preview
    try:
        pix = page.get_pixmap(dpi=150)
        st.image(pix.tobytes("png"), caption=f"{uf.name} – page 1 preview", use_column_width=True)
    except Exception as e:
        st.warning(f"Preview failed for {uf.name}: {e}")






