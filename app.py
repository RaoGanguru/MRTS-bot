


import streamlit as st
import pymupdf as fitz  # PyMuPDF
import re

st.set_page_config(page_title="MRTS Bot – Reliable PDF Search", layout="wide")
st.title("MRTS Bot – Reliable PDF Search")

# -------------------- Upload PDFs --------------------
uploaded_files = st.file_uploader(
    "Upload one or more PDFs",
    type=["pdf"],
    accept_multiple_files=True,
)

if not uploaded_files:
    st.info("Upload PDFs to enable search.")
    st.stop()

# -------------------- Caching helpers --------------------
@st.cache_data(show_spinner=True)
def open_doc(bytes_):
    return fitz.open(stream=bytes_, filetype="pdf")

@st.cache_data(show_spinner=True)
def get_page_text(bytes_, pno: int, sort: bool = True) -> str:
    """Plain text per page; sort=True improves reading order in many files."""
    doc = open_doc(bytes_)
    return doc[pno].get_text("text", sort=sort) or ""

@st.cache_data(show_spinner=False)
def render_preview(bytes_, pno: int, dpi: int = 150) -> bytes:
    """PNG preview of a page."""
    doc = open_doc(bytes_)
    return doc[pno].get_pixmap(dpi=dpi).tobytes("png")

# Build in-memory list of documents
docs = [{"name": uf.name, "bytes": uf.getvalue(), "doc": open_doc(uf.getvalue())} for uf in uploaded_files]

st.success(f"Loaded {len(docs)} file(s).")

# -------------------- Search UI --------------------
st.subheader("Search")
q = st.text_input("Enter word/phrase", "", placeholder="e.g., standard, clause 5.3, AS/NZS 1234")
advanced = st.checkbox("Show advanced options", value=False)
use_fallback = st.checkbox("Use fallback (regex on extracted text) if native search finds nothing", value=True)
find_rotated = st.checkbox("Find rotated/tilted text (use quadrilaterals)", value=False) if advanced else False

if not q:
    st.info("Type a search term above and press Enter.")
    st.stop()

# Compile fallback regex only if needed
rx = None
if use_fallback:
    # Case-insensitive regex for fallback search; escapes user text by default
    pattern = re.escape(q)
    rx = re.compile(pattern, flags=re.IGNORECASE)

# -------------------- Do the search --------------------
def make_snippet(page, rect_or_quad, ctx_chars=80) -> str:
    """
    Extract a readable snippet around the hit using a clip.
    For quads, use bounding rect; for rects, use as-is.
    """
    clip = rect_or_quad.rect if hasattr(rect_or_quad, "rect") else rect_or_quad
    snippet = page.get_text("text", clip=clip) or ""
    # Compact whitespace and emphasize the query visually
    snippet = re.sub(r"\s+", " ", snippet).strip()
    # Try to bold the first occurrence; case-insensitive replacement
    try:
        i = re.search(re.escape(q), snippet, flags=re.IGNORECASE)
        if i:
            start, end = i.span()
            snippet = snippet[:start] + "**" + snippet[start:end] + "**" + snippet[end:]
    except Exception:
        pass
    return snippet[:ctx_chars] + ("…" if len(snippet) > ctx_chars else "")

results = []
for d in docs:
    name, bytes_, doc = d["name"], d["bytes"], d["doc"]
    for pno in range(doc.page_count):
        page = doc[pno]

        # --- Primary: MuPDF native search (robust to hyphenation/ligatures; case-insensitive by default) ---
        # Tip: search_for returns rectangles; quads=True returns quadrilaterals for rotated text. [1](https://artifex.com/blog/explore-text-searching-with-pymupdf)
        hits = page.search_for(q, quads=find_rotated)
        if not hits and use_fallback:
            # --- Fallback: regex on extracted plain text ---
            text = get_page_text(bytes_, pno, sort=True)  # sort=True tends to help reading order. [4](https://pymupdftest.readthedocs.io/en/stable/app1.html)
            if rx and rx.search(text):
                # Build a pseudo-hit: use entire page as clip for snippet
                results.append({
                    "file": name,
                    "page": pno + 1,
                    "count": len(rx.findall(text)) if rx else 1,
                    "snippet": (re.sub(r"\s+", " ", text)[:120] + "…") if text else "",
                    "mode": "fallback",
                    "preview_bytes": render_preview(bytes_, pno),
                })
            continue

        if hits:
            # Generate one row per page (show first snippet; count = #hits)
            snippet = make_snippet(page, hits[0])
            results.append({
                "file": name,
                "page": pno + 1,
                "count": len(hits),
                "snippet": snippet,
                "mode": "native",
                "preview_bytes": render_preview(bytes_, pno),
            })

# -------------------- Show results --------------------
st.subheader("Results")
if not results:
    st.warning("No matches found.")
    st.stop()

# Summary table
st.dataframe(
    [{"file": r["file"], "page": r["page"], "matches": r["count"], "snippet": r["snippet"], "mode": r["mode"]} for r in results],
    use_container_width=True,
    hide_index=True,
)

# Preview selector
choice = st.selectbox(
    "Preview a matched page",
    options=[f"{r['file']} – page {r['page']} ({r['count']} match/es; {r['mode']})" for r in results],
    index=0,
)
chosen = next(r for r in results if f"{r['file']} – page {r['page']} ({r['count']} match/es; {r['mode']})" == choice)

col_img, col_text = st.columns([2, 3])
with col_img:
    st.image(chosen["preview_bytes"], caption=f"{chosen['file']} – page {chosen['page']}", use_column_width=True)
with col_text:
    # Show full page text when fallback found it; otherwise re-extract for context
    page_text = get_page_text(next(d["bytes"] for d in docs if d["name"] == chosen["file"]), chosen["page"] - 1, sort=True)
    st.text_area("Full page text", page_text, height=400)

st.download_button(
    "Download results (CSV)",
    data="file,page,count,mode,snippet\n" + "\n".join(
        f"{r['file']},{r['page']},{r['count']},{r['mode']},{r['snippet'].replace(',', ' ').replace('\n',' ')}" for r in results
    ),
    file_name="search_results.csv",
    mime="text/csv",
)


