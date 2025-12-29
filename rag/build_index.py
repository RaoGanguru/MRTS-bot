
import os
import json
from pathlib import Path
from dotenv import load_dotenv
import numpy as np
import faiss

# PDF extraction
import pymupdf4llm  # optional; else use pymupdf directly [3](https://pypi.org/project/pymupdf4llm/)
import fitz          # PyMuPDF [1](https://pymupdftest.readthedocs.io/en/stable/app1.html)

# Embeddings
from sentence_transformers import SentenceTransformer  # [12](https://www.aitude.com/the-ultimate-guide-to-faiss-indexing-with-sentence-transformers-for-semantic-search/)

load_dotenv()
SPECS_DIR = Path(os.getenv("SPECS_DIR", "./data/specs"))
DRAWINGS_DIR = Path(os.getenv("DRAWINGS_DIR", "./data/drawings"))
INDEX_DIR = Path(os.getenv("INDEX_DIR", "./data/index"))
INDEX_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1500))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 200))

EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
model = SentenceTransformer(EMBED_MODEL)

def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append(text[start:end])
        if end == len(text): break
        start = end - overlap
    return chunks

def extract_pages(path: Path):
    # Prefer PyMuPDF4LLM page_chunks; fallback to plain text
    try:
        pages = pymupdf4llm.to_markdown(path.as_posix(), page_chunks=True)  # list of dicts (text, page) [16](https://deepwiki.com/pymupdf/RAG/6-examples)
        return [{"page": p["page"]+1, "text": p["text"]} for p in pages]
    except Exception:
        doc = fitz.open(path.as_posix())
        out = []
        for i in range(doc.page_count):
            t = doc[i].get_text("text", sort=True)
            out.append({"page": i+1, "text": t})
        return out

def collect_documents():
    pdfs = list(SPECS_DIR.glob("*.pdf")) + list(DRAWINGS_DIR.glob("*.pdf"))
    docs = []  # each item: {text, meta:{spec, page}}
    for pdf in pdfs:
        for p in extract_pages(pdf):
            for c in chunk_text(p["text"]):
                if not c.strip(): continue
                docs.append({"text": c, "meta": {"spec": pdf.name, "page": p["page"]}})
    return docs

def build_faiss(docs):
    texts = [d["text"] for d in docs]
    embs  = model.encode(texts, convert_to_numpy=True).astype("float32")
    dim   = embs.shape[1]
    index = faiss.IndexFlatL2(dim)  # exact L2; upgrade to IVF/HNSW later for scale [4](https://faiss.ai/)
    index.add(embs)

    # Save index & docstore
    faiss.write_index(index, (INDEX_DIR / "faiss.index").as_posix())  # [5](https://github.com/facebookresearch/faiss/wiki/Index-IO,-cloning-and-hyper-parameter-tuning)
    with open(INDEX_DIR / "docstore.json", "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False)

    # meta
    meta = {"embedding_model": EMBED_MODEL, "dim": dim, "count": len(texts)}
    with open(INDEX_DIR / "meta.json", "w") as f:
        json.dump(meta, f)
    print(f"Saved {len(texts)} chunks to {INDEX_DIR}")

if __name__ == "__main__":
    docs = collect_documents()
    build_faiss(docs)
