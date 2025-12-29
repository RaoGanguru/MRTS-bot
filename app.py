

import streamlit as st
import re
from typing import List, Dict, Any

# Use modern import; keeps "fitz" alias for convenience
import pymupdf as fitz  # PyMuPDF

# ---------- Streamlit page ----------
st.set_page_config(page_title="MRTS Bot – PDF Search", layout="wide")
st.title("MRTS Bot – Search within PDFs")

# ---------- Upload PDFs ----------
uploaded_files = st.file_uploader(
    "Upload one or more PDFs",
    type=["pdf"],
    accept_multiple_files=True,
    help="You can add multiple standard (text) PDFs. Scanned/image-only PDFs require OCR (not enabled here).",
)

if not uploaded_files:
    st.info("Upload PDFs to enable search.")
    st.stop()

# ---------- Cache text extraction ----------
@st.cache_data(show_spinner=True)
def extract_pages(file_bytes: bytes) -> List[str]:
    """
    Returns a list of page texts for the given PDF bytes.
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []
    for i in range(doc.page_count):
        page = doc[i]
        # 'text' mode gives plain text; you can also try 'blocks'/'words' for structured output
        pages.append(page.get_text("text") or "")
    return pages

@st.cache_data(show_spinner=False)
def render_preview(file_bytes: bytes, page_no: int, dpi: int = 150) -> bytes:
    """
    Returns a PNG image (bytes) for the given PDF page at the chosen DPI.
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pix = doc[page_no].get_pixmap(dpi=dpi)
    return pix.tobytes("png")

# ---------- Build an in-memory index ----------
index: Dict[str, Dict[str, Any]] = {}
for uf in uploaded_files:
    # Key with filename only for display; store bytes for preview rendering
    index[uf.name] = {
        "bytes": uf.read(),
        "pages": extract_pages(uf.getvalue()),  # uses cache
    }

st.success(f"Indexed {len(index)} file(s).")

# ---------- Search UI ----------
st.subheader("Search")
col_q, col_case, col_word, col_rx = st.columns([4, 1.2, 1.2, 1.2])
with col_q:
    query = st.text_input("Enter word/phrase", value="", placeholder="e.g. standard, clause 5.3, AS/NZS 1234")
with col_case:
    case_sensitive = st.checkbox("Case-sensitive", value=False)
with col_word:
    whole_word = st.checkbox("Whole word", value=False)
with col_rx:
    use_regex = st.checkbox("Regex", value=False, help="Advanced searches; e.g. 'clause\\s+5\\.(\\d+)'")

if not query:
    st.info("Type a search term above and press Enter.")
    st.stop()

# ---------- Compile a search pattern ----------
flags = 0 if case_sensitive else re.IGNORECASE
if use_regex:
    pattern = query
else:
    pattern = re.escape(query)

if whole_word and not use_regex:
    pattern = rf"\b{pattern}\b"

try:
    rx = re.compile(pattern, flags)
except re.error as e:
    st.error(f"Invalid regex: {e}")
    st.stop()

# ---------- Run search over all pages ----------
def make_snippet(text: str, m: re.Match, ctx: int = 60) -> str:
    """Return a short snippet around the match, with the match emphasized."""
    start, end = m.start(), m.end()
    left = max(0, start - ctx)
    right = min(len(text), end + ctx)
    snippet = text[left:start] + "**" + text[start:end] + "**" + text[end:right]
    # Add ellipses when we trimmed
    if left > 0:
        snippet = "…" + snippet
    if right < len(text):
        snippet = snippet + "…"
    # Compress whitespace for nicer display
    snippet = re.sub(r"\s+", " ", snippet).strip()
    return snippet

results: List[Dict[str, Any]] = []
for fname, payload in index.items():
    pages = payload["pages"]
    for pno, ptext in enumerate(pages):
        matches = list(rx.finditer(ptext))
        if not matches:
            continue
        # Add one result row per page, showing first snippet + count
        first_snip = make_snippet(ptext, matches[0])
        results.append({
            "file": fname,
            "page": pno + 1,
            "matches": len(matches),
            "snippet": first_snip,
        })

# ---------- Show results ----------
st.subheader("Results")
if not results:
    st.warning("No matches found.")
    st.stop()

# Display summary table
st.dataframe(
    results,
    use_container_width=True,
    hide_index=True,
)

# Select a result to preview
st.markdown("**Preview a matched page**")
sel = st.selectbox(
    "Choose file/page to preview",
    options=[f"{r['file']} – page {r['page']} ({r['matches']} match/es)" for r in results],
    index=0,
)

# Find the chosen result row
chosen = next(r for r in results if f"{r['file']} – page {r['page']} ({r['matches']} match/es)" == sel)
file_bytes = index[chosen["file"]]["bytes"]
page_no = chosen["page"] - 1

# Render preview and show full page text (optional)
cols = st.columns([2, 3])
with cols[0]:
    try:
        png = render_preview(file_bytes, page_no, dpi=150)
        st.image(png, caption=f"{chosen['file']} – page {chosen['page']}", use_column_width=True)
    except Exception as e:
        st.warning(f"Preview failed: {e}")

with cols[1]:
    # Show the full page text (helpful for reading context)
    full_text = index[chosen["file"]]["pages"][page_no]
    st.text_area("Full page text", full_text, height=400)

# Optional: allow results download as CSV
csv_lines = ["file,page,matches,snippet"]
for r in results:
    # Escape any commas/newlines in snippet
    snip = r["snippet"].replace("\n", " ").replace(",", " ")
    csv_lines.append(f"{r['file']},{r['page']},{r['matches']},{snip}")
csv_data = "\n".join(csv_lines)

st.download_button(
    label="Download results (CSV)",
    data=csv_data,
    file_name="pdf_search_results.csv",
    mime="text/csv",
)


