
import os, json
from pathlib import Path
from dotenv import load_dotenv
import numpy as np
import faiss

from rag.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from rag.llm import answer

load_dotenv()
INDEX_DIR = Path(os.getenv("INDEX_DIR", "./data/index"))
TOP_K = int(os.getenv("TOP_K", 5))

# Load index + docstore
INDEX = faiss.read_index((INDEX_DIR / "faiss.index").as_posix())    # [5](https://github.com/facebookresearch/faiss/wiki/Index-IO,-cloning-and-hyper-parameter-tuning)
DOCS  = json.loads((INDEX_DIR / "docstore.json").read_text(encoding="utf-8"))

# Recreate embedding model for queries (must match build_index)
from sentence_transformers import SentenceTransformer
EMBED_MODEL = json.loads((INDEX_DIR / "meta.json").read_text())["embedding_model"]
EMB = SentenceTransformer(EMBED_MODEL)

def search(query: str, k: int = TOP_K):
    q = EMB.encode([query], convert_to_numpy=True).astype("float32")
    distances, idxs = INDEX.search(q, k)  # (1,k)
    hits = []
    for i, d in zip(idxs[0], distances[0]):
        doc = DOCS[i]
        hits.append({"text": doc["text"], "spec": doc["meta"]["spec"], "page": doc["meta"]["page"], "score": float(d)})
    return hits

def compose_context(hits):
    # include (spec,page) metadata inline; model must surface citations
    blocks = []
    for h in hits:
        blocks.append(f"[{h['spec']} p.{h['page']}] {h['text']}")
    return "\n\n".join(blocks)

def qa(query: str) -> str:
    hits = search(query)
    ctx = compose_context(hits)
    prompt = USER_PROMPT_TEMPLATE.format(question=query, context=ctx)
    return answer(SYSTEM_PROMPT, prompt), hits
