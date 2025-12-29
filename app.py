

import streamlit as st
from rag.retrieval import qa

st.set_page_config(page_title="TMR MRTS Bot", layout="wide")
st.title("TMR MRTS Bot – RAG over MRTS specs & drawings")

query = st.text_input("Ask a question (e.g., permissible tolerances, clause references, drawing details):")
run = st.button("Search & Answer")

if run and query:
    with st.spinner("Retrieving…"):
        ans, hits = qa(query)

    st.subheader("Answer")
    st.write(ans)

    st.subheader("Top matches")
    for i, h in enumerate(hits, 1):
        with st.expander(f"{i}. {h['spec']} — page {h['page']} (score={h['score']:.3f})"):
            st.write(h["text"])




