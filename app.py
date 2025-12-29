
import streamlit as st
import pymupdf as fitz  # PyMuPDF
from pathlib import Path
import re

st.set_page_config(page_title="MRTS Bot – Repo PDFs Search", layout="wide")
st.title("MRTS Bot – Search standards (no uploads)")

# ---------- Locate PDFs in repo ----------
# On Streamlit Cloud, your repo is copied under /mount/src, and your app runs from repo root.
# We'll look under mrts-bot/pdfs/ for *.pdf files. [1](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization)
PDF_DIR = Path("/mount/src/mrts-bot/pdfs")
if not PDF_DIR.exists():
    st.error(f"Folder not found: {PDF_DIR}. Create it and add your PDFs.")
    st.stop()

pdf_paths = sorted(PDF_DIR.glob("*.pdf"))
if not pdf_paths:
    st.warning(f"No PDFs found under {PDF_DIR}.")
    st.stop()

# ---------- Cache resources (Documents) & data (text/image) ----------
# Use cache_resource for PyMuPDF Document objects (unserializable singletons). [2](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies)
@st.cache_resource(show_spinner=True)
def open_doc(path: Path) -> fitz.Document:
    return fitz.open(path.as_posix())

# Use cache_data for serializable outputs (text strings, PNG bytes). [3](https://pymupdftest.readthedocs.io/en/stable/installation.html)
@st.cache_data(show_spinner=False)
def get_page_text(path: Path, pno: int, sort: bool = True) -> str:
    doc = fitz.open(path.as_posix())
    return doc[pno].get_text("text", sort=sort) or ""

@st.cache_data(show_spinner=False)
def render_preview(path: Path, pno: int, dpi: int = 150) -> bytes:
    doc = fitz.open(path.as_posix())
    return doc[pno].get_pixmap(dpi=dpi).tobytes("png")

# ---------- UI: pick files & search ----------
left, right = st.columns([2, 3])
with left:
    chosen_files = st.multiselect(
        "Choose PDFs to search",
        options=[p.name for p in pdf_paths],
        default=[p.name for p in pdf_paths],  # all by default
    )
with right:
    query = st.text_input("Search term", "", placeholder="e.g., standard, clause 5.3, AS/NZS 1234")
    find_rotated = st.checkbox("Find rotated/tilted text (quads=True)", value=False)

if not chosen_files or not query:
    st.info("Select at least one PDF and enter a search term.")
    st.stop()

selected_paths = [p for p in pdf_paths if p.name in chosen_files]

# ---------- Run robust native search across all selected PDFs ----------
results = []
for path in selected_paths:
    doc = open_doc(path)  # cached resource
    for pno in range(doc.page_count):
        page = doc[pno]
        hits = page.search_for(query, quads=find_rotated)
        # Native search: case-insensitive by default; handles hyphenation/ligatures. [12](https://stackabuse.com/bytes/python-how-to-specify-a-github-repo-in-requirements-txt/)[13](https://www.geeksforgeeks.org/python/overview-of-requirementstxt-and-direct-github-sources/)
        if hits:
            # Make snippet by clipping around first hit
            clip = hits[0].rect if hasattr(hits[0], "rect") else hits[0]
            snippet = page.get_text("text", clip=clip) or ""
            snippet = re.sub(r"\s+", " ", snippet).strip()
            results.append({
                "file": path.name,
                "page": pno + 1,
                "matches": len(hits),
                "snippet": snippet[:120] + ("…" if len(snippet) > 120 else ""),
            })

st.subheader("Results")
if not results:
    st.warning("No matches found.")
    st.stop()

st.dataframe(results, use_container_width=True, hide_index=True)

sel = st.selectbox(
    "Preview a matched page",
    options=[f"{r['file']} – page {r['page']} ({r['matches']} match/es)" for r in results],
    index=0,
)

chosen = next(r for r in results if f"{r['file']} – page {r['page']} ({r['matches']} match/es)" == sel)
p = next(p for p in selected_paths if p.name == chosen["file"])
png = render_preview(p, chosen["page"] - 1, dpi=150)
col_img, col_text = st.columns([2, 3])
with col_img:
    st.image(png, caption=f"{chosen['file']} – page {chosen['page']}", use_column_width=True)
with col_text:
    full_text = get_page_text(p, chosen["page"] - 1, sort=True)  # reading order often improves with sort=True [14](https://github.com/RaoGanguru/MRTS-Compliance-tool)
    st.text_area("Full page text", full_text, height=400)



