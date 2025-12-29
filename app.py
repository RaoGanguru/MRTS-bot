
import streamlit as st
import sys
import importlib.util

# --- Robust import: prefer modern 'pymupdf', fall back to legacy 'fitz' ---
try:
    import pymupdf as fitz  # Recommended since PyMuPDF 1.24.3
except ModuleNotFoundError:
    try:
        import fitz  # Backward-compatible alias provided by PyMuPDF
    except ModuleNotFoundError as e:
        # Clear message if dependencies weren't installed
        raise RuntimeError(
            "PyMuPDF is not installed. Add 'PyMuPDF' to requirements.txt "
            "placed in the repo root or in the same folder as this app (mrts-bot/), "
            "then redeploy."
        ) from e

from io import BytesIO

# --- Page setup & diagnostics ---
st.set_page_config(page_title="MRTS Bot – PDF Viewer", layout="wide")
st.title("MRTS Bot")

py_version = sys.version.replace("\n", " ")
st.caption(f"Python: {py_version}")
st.caption(f"pymupdf spec found: {importlib.util.find_spec('pymupdf') is not None}")
st.caption(f"fitz spec found: {importlib.util.find_spec('fitz') is not None}")
st.caption(f"PyMuPDF version: {getattr(fitz, '__version__', 'unknown')}")

uploaded_file = st.file_uploader("Upload a PDF file", type=["pdf"])
if not uploaded_file:
    st.info("Upload a PDF to extract and preview its content.")
    st.stop()

# --- Open the uploaded PDF with PyMuPDF ---
try:
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
except Exception as e:
    st.error(f"Could not open PDF: {e}")
    st.stop()

# --- Document info ---
st.subheader("Document info")
st.write({"pages": doc.page_count})

# --- Extract text from first page ---
st.subheader("First page text")
try:
    page = doc[0]
    text = page.get_text()
    st.text_area("Text extracted from page 1", text, height=300)

    st.download_button(
        "Download extracted text",
        data=text or "",
        file_name=f"{uploaded_file.name.rsplit('.',1)[0]}_page1.txt",
        mime="text/plain",
    )
except Exception as e:
    st.warning(f"Text extraction failed: {e}")

# --- Render preview of first page ---
st.subheader("First page preview")
try:
    pix = page.get_pixmap(dpi=150)
    st.image(pix.tobytes("png"), caption="Page 1 preview", use_column_width=True)
except Exception as e:
    st.warning(f"Page preview failed: {e}")

st.success("Done.")

