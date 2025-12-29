
import streamlit as st
import pymupdf as fitz  # modern import; keeps any existing 'fitz.' calls working
from io import BytesIO

# --- Streamlit page setup ---
st.set_page_config(page_title="MRTS Bot – PDF Viewer", layout="wide")
st.title("MRTS Bot")

# Show PyMuPDF version so we can confirm the module is installed
st.caption(f"PyMuPDF version: {getattr(fitz, '__version__', 'unknown')}")

# --- File upload UI ---
uploaded_file = st.file_uploader("Upload a PDF file", type=["pdf"])

if uploaded_file is None:
    st.info("Upload a PDF to extract and preview its content.")
    st.stop()

# --- Open the uploaded PDF safely with PyMuPDF ---
try:
    pdf_bytes = uploaded_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
except Exception as e:
    st.error(f"Could not open PDF: {e}")
    st.stop()

# --- Basic document info ---
st.subheader("Document info")
st.write({"pages": doc.page_count})

# --- Extract text from the first page ---
st.subheader("First page text")
try:
    first_page = doc[0]
    text = first_page.get_text()
    st.text_area("Text extracted from page 1", text, height=300)

    # Offer a download of extracted text
    st.download_button(
        label="Download extracted text",
        data=text or "",
        file_name=f"{uploaded_file.name.rsplit('.',1)[0]}_page1.txt",
        mime="text/plain",
    )
except Exception as e:
    st.warning(f"Text extraction failed: {e}")

# --- Render a preview image of the first page ---
st.subheader("First page preview")
try:
    # Render a PNG preview at a reasonable resolution
    pix = first_page.get_pixmap(dpi=150)
    png_bytes = pix.tobytes("png")
    st.image(png_bytes, caption="Page 1 preview", use_column_width=True)
except Exception as e:
    st.warning(f"Page preview failed: {e}")

st.success("Done.")
``

