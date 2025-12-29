
# app.py — Single-file Streamlit app (super simple)
# Runs on Streamlit Community Cloud. Upload PDFs, build index, ask questions, download PDF.
# Uses a tiny "naive" embedding for demo (we’ll improve later). Chat via OpenRouter (free tier).
# Your API key will be added in Step 4 using Streamlit "Secrets".

import streamlit as st
from pathlib import Path
import os, io, re, json
import fitz  # PyMuPDF
import numpy as np
import faiss
import requests
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from textwrap import wrap

# ----------------------------
# UI setup
# ----------------------------
st.set_page_config(page_title="TMR MRTS QA", layout="wide")
st.title("TMR MRTS & Standard Drawings QA (Public Link)")

# ----------------------------
# Helper: LLM via OpenRouter
# ----------------------------
OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY", None)
LLM_MODEL = st.secrets.get("LLM_MODEL", "meta-llama/llama-3.3-8b-instruct")

SYSTEM_PROMPT = """You are a TMR site-engineering assistant for MRTS, Standard Drawings and Tech Notes.
Answer ONLY from provided context. If missing, say what doc/version is needed.
- Return concise answers, THEN bullet references in [DOC_ID clause/page] and drawing IDs and table/footnotes.
- Do NOT invent values; no design advice. Drawings must be certified fit-for-purpose by RPEQ.
- If multiple versions conflict, warn and ask for the project-pinned version."""

def llm_chat(messages, temperature=0.2):
    if not OPENROUTER_API_KEY:
        return "Missing OpenRouter API key. Ask your admin to set OPENROUTER_API_KEY in Streamlit Secrets."
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
    payload = {"model": LLM_MODEL, "messages": messages, "temperature": temperature}
    r = requests.post(url, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# ----------------------------
# Indexing (single-file, simple)
# ----------------------------
DATA_DIR = Path("data")
INDEX_DIR = DATA_DIR / "index"
SPEC_DIR = DATA_DIR / "specs"
DRAW_DIR = DATA_DIR / "drawings"
for p in [INDEX_DIR, SPEC_DIR, DRAW_DIR]:
    p.mkdir(parents=True, exist_ok=True)

CLAUSE_PATTERNS = [r"^\s*\d+(\.\d+)+\s+.+", r"^\s*HOLD POINTS?\s*$", r"^\s*WITNESS POINTS?\s*$", r"^\s*ANNEXURE\s+[A-Z]+.*$"]
DRAWING_ID = r"\bSD\d{3,4}\b"
TABLE_CAPTION = r"^Table\s+\d+[\-–]\d+"
FOOTNOTE_LINE = r"^\s*Note(\s*\([a-z]\))?:"

def extract_pdf_pages(pdf_path: Path):
    doc = fitz.open(pdf_path)
    out = [{"page_num": i+1, "text": doc[i].get_text("text")} for i in range(len(doc))]
    doc.close()
    return out

def split_chunks(page_text: str, max_chars=900):
    lines = page_text.splitlines()
    chunks, cur = [], []
    meta_block = {"table": None, "footnote": None}
    def push():
        if cur:
            t = "\n".join(cur).strip()
            if len(t) > 60:
                chunks.append({"text": t, "table": meta_block["table"], "footnote": meta_block["footnote"]})
    for ln in lines:
        if re.match(TABLE_CAPTION, ln.strip()):
            meta_block["table"] = ln.strip()
        if re.match(FOOTNOTE_LINE, ln.strip()):
            meta_block["footnote"] = ln.strip()
        if any(re.match(p, ln.strip()) for p in CLAUSE_PATTERNS) and len("\n".join(cur)) > 200:
            push(); cur = [ln]; meta_block = {"table": meta_block["table"], "footnote": meta_block["footnote"]}
        else:
            cur.append(ln)
        if len("\n".join(cur)) >= max_chars:
            push(); cur = []
    push()
    return chunks

def guess_doc_id(filename: str) -> str:
    m = re.search(r"(MRTS\d+|MRS\d+|SD\d{3,4})", filename.upper())
    return m.group(1) if m else Path(filename).stem

def naive_embed(texts):
    # Tiny, free demo embedding: converts text bytes to fixed-length numeric vectors.
    # Not perfect, but good enough to get the app working. We can upgrade later.
    vecs = []
    for t in texts:
        arr = np.frombuffer(t.encode("utf-8"), dtype=np.uint8).astype(np.float32)
        if arr.size == 0: arr = np.zeros(8, dtype=np.float32)
        if arr.size < 256:
            arr = np.pad(arr, (0,256-arr.size))
        else:
            arr = arr[:256]
        vecs.append(arr)
    return np.stack(vecs)

def build_index():
    texts, metas = [], []
    for sub in ["specs", "drawings"]:
        folder = DATA_DIR / sub
        if not folder.exists(): continue
        for pdf in folder.glob("*.pdf"):
            pages = extract_pdf_pages(pdf)
            base_id = guess_doc_id(pdf.name)
            for p in pages:
                for ch in split_chunks(p["text"]):
                    clause = None
                    m = re.search(r"^(\d+(\.\d+)+)\s+.+$", ch["text"], flags=re.M)
                    if m: clause = m.group(1)
                    draw = None
                    dm = re.search(DRAWING_ID, ch["text"])
                    if dm: draw = dm.group(0)
                    metas.append({
                        "doc_id": base_id, "file_name": pdf.name, "page": p["page_num"], "clause": clause,
                        "drawing": draw, "category": sub, "table": ch["table"], "footnote": ch["footnote"]
                    })
                    texts.append(ch["text"])
    if not texts:
        return False
    vecs = naive_embed(texts)
    dim = vecs.shape[1]
    index = faiss.IndexFlatIP(dim)
    faiss.normalize_L2(vecs)
    index.add(vecs)
    faiss.write_index(index, str(INDEX_DIR / "faiss.index"))
    with open(INDEX_DIR / "docstore.json","w") as f:
        json.dump({"texts": texts, "metas": metas}, f, indent=2)
    return True

def embed_query(q):
    v = naive_embed([q]); faiss.normalize_L2(v); return v

def top_k(query, k=6, doc_id_filters=None, category_filters=None):
    index = faiss.read_index(str(INDEX_DIR / "faiss.index"))
    with open(INDEX_DIR / "docstore.json") as f: store = json.load(f)
    vec = embed_query(query)
    D, I = index.search(vec, k*4)
    contexts = []
    for idx, score in zip(I[0], D[0]):
        m = store["metas"][idx]; t = store["texts"][idx]
        if doc_id_filters and m["doc_id"] not in doc_id_filters: continue
        if category_filters and m["category"] not in category_filters: continue
        contexts.append({"text": t, "meta": m, "score": float(score)})
        if len(contexts) >= k: break
    return contexts

# ----------------------------
# Prompt composer
# ----------------------------
def compose_user_prompt(question:str, contexts:list, inputs:dict=None):
    ctx_txts = []
    for c in contexts:
        m = c["meta"]
        head = f"[{m.get('doc_id')} p.{m.get('page')} {m.get('clause') or ''} {m.get('drawing') or ''} {m.get('table') or ''} {m.get('footnote') or ''}]"
        ctx_txts.append(f"{head}\n{c['text']}")
    ctx_block = "\n\n".join(ctx_txts)
    extra = f"\nInputs: {inputs}" if inputs else ""
    return f"Question: {question}{extra}\n\nContext:\n{ctx_block}\n\nReturn the answer + bullet references."

# ----------------------------
# PDF export
# ----------------------------
def make_pdf(question, inputs, answer, refs):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4); w,h = A4; y = h - 40
    def draw_line(text, leading=14):
        nonlocal y
        for ln in wrap(text, 100):
            c.drawString(40, y, ln); y -= leading
            if y < 60: c.showPage(); y = h - 40
    c.setFont("Helvetica-Bold", 14); draw_line("TMR MRTS & Standard Drawings QA")
    c.setFont("Helvetica", 11); draw_line(f"Question: {question}")
    if inputs:
        draw_line("Inputs:")
        for k,v in inputs.items(): draw_line(f"  - {k}: {v}")
    draw_line("Answer:"); draw_line(answer)
    draw_line("References:")
    for r in refs: draw_line(f"  - {r}")
    draw_line("")
    draw_line("Notes: Standard Drawings require RPEQ certification for fitness for purpose.")
    draw_line("Updated content does not automatically apply to in-progress contracts; confirm project-pinned versions.")
    c.save(); pdf = buf.getvalue(); buf.close()
    return pdf

# ----------------------------
# Intent + culvert form
# ----------------------------
def detect_intent(q:str):
    ql = q.lower()
    if any(k in ql for k in ["culvert","box culvert","slab deck","pipe culvert"]): return "culvert"
    if any(k in ql for k in ["guardrail","barrier","road furniture"]): return "guardrail"
    if "eme" in ql or "high modulus asphalt" in ql: return "eme"
    if "stabilis" in ql: return "stabilisation"
    return "generic"

def culvert_form():
    st.info("Please provide a few details so we return the exact specs/drawings.")
    ctype = st.selectbox("Culvert type", ["Box","Slab deck","Pipe"])
    size  = st.text_input("Size", placeholder="e.g., 2500×1200 or DN600")
    fish  = st.selectbox("Fish passage (ADR mapping)", ["None/Unmapped","Amber","Red"])
    heads = st.selectbox("Headwalls/Wings", ["Precast","Cast-in-place","Undecided"])
    load  = st.text_input("Road class / cover", placeholder="e.g., collector / 300 mm cover")
    notes = st.text_area("Site notes (optional)", placeholder="utilities, skew, gradient...")
    return {"type":ctype,"size":size,"fish":fish,"headwalls":heads,"load":load,"notes":notes}

# ----------------------------
# Sidebar: upload + build index
# ----------------------------
st.sidebar.header("Upload PDFs")
specs = st.sidebar.file_uploader("MRTS/MRS PDFs", type=["pdf"], accept_multiple_files=True)
draws = st.sidebar.file_uploader("Standard Drawings PDFs", type=["pdf"], accept_multiple_files=True)

if specs:
    for f in specs:
        with open(SPEC_DIR / f.name, "wb") as out: out.write(f.read())
if draws:
    for f in draws:
        with open(DRAW_DIR / f.name, "wb") as out: out.write(f.read())

if st.sidebar.button("Build/Update Index"):
    with st.spinner("Indexing documents..."):
        ok = build_index()
    st.sidebar.success("Index built." if ok else "No documents found.")

# ----------------------------
# Main Q&A
# ----------------------------
q = st.text_input("Ask your question (e.g., 'EME thickness tolerance', 'I want to build a culvert')")
k = st.slider("Top K (context size)", 3, 12, 6)
inputs = None

if q.strip():
    intent = detect_intent(q)
    if intent == "culvert":
        inputs = culvert_form()
        go = st.button("Use these inputs")
    else:
        go = st.button("Search now")

    if go:
        if intent == "culvert":
            culv_docs = ["MRTS03","MRTS24","MRTS25","MRTS26"]
            ctxs = top_k(q, k*2, None, None)
            pruned = [c for c in ctxs if (c["meta"]["doc_id"] in culv_docs)]
            draw_targets = ["SD1240","SD1250","SD1260"]
            if inputs.get("fish") in ["Amber","Red"]: draw_targets += ["SD1270","SD1271"]
            pruned += [c for c in ctxs if c["meta"]["doc_id"] in draw_targets]
            if len(pruned) < k: pruned += ctxs[:k-len(pruned)]
            contexts = pruned[:k]
        else:
            contexts = top_k(q, k, None, None)

        prompt = compose_user_prompt(q, contexts, inputs)
        ans = llm_chat([{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":prompt}])

        st.subheader("Answer"); st.write(ans)
        st.subheader("References")
        refs = []
        for c in contexts:
            m = c["meta"]
            ref = f"{m['doc_id']} `{m['file_name']}` p.{m['page']} clause {m.get('clause') or '—'} drawing {m.get('drawing') or '—'} {m.get('table') or ''} {m.get('footnote') or ''} (score {c['score']:.3f})"
            st.markdown(f"- {ref}"); refs.append(ref)

        pdf = make_pdf(q, inputs, ans, refs)
        st.download_button("Download Q&A as PDF", data=pdf, file_name="tmr_answer.pdf", mime="application/pdf")

st.divider()
st.markdown("**Official TMR sources:**")
st.markdown("- [Specifications portal](https://www.tmr.qld.gov.au/business-industry/Technical-standards-publications/Specifications)")
st.markdown("- [Overarching specs (MRTS01/MRTS02/MRTS50/MRTS56)](https://www.tmr.qld.gov.au/business-industry/technical-standards-publications/specifications/1-overarching-specifications)")
st.markdown("- [Standard drawings (roads)](https://www.tmr.qld.gov.au/business-industry/technical-standards-publications/standard-drawings-roads)")
st.markdown("- [Drawings index (IDs like SD1240/1270)](https://www.tmr.qld.gov.au/business-industry/Technical-standards-publications/Standard-drawings-roads/Standard-drawings-index.aspx)")
