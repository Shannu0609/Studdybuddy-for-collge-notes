"""RAG core: extract -> chunk -> embed (Chroma default MiniLM) -> retrieve -> LLM.
Swap this file's functions with your own existing RAG code if you like."""
import os, io, uuid
import chromadb, anthropic
from pypdf import PdfReader

client = chromadb.PersistentClient(path="data/chroma")
llm = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY
MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5")

def _col(user_id):
    return client.get_or_create_collection(f"user_{user_id}")

def extract(filename, data: bytes):
    """Returns list of (page_label, text)."""
    if filename.lower().endswith(".pdf"):
        r = PdfReader(io.BytesIO(data))
        return [(f"p.{i+1}", p.extract_text() or "") for i, p in enumerate(r.pages)]
    return [("", data.decode("utf-8", errors="ignore"))]

def chunk(text, size=220, overlap=40):
    w = text.split()
    for i in range(0, len(w), size - overlap):
        piece = " ".join(w[i:i + size])
        if piece.strip():
            yield piece

def index_file(user_id, doc_id, filename, data: bytes):
    col, ids, docs, metas = _col(user_id), [], [], []
    for page, text in extract(filename, data):
        for c in chunk(text):
            ids.append(str(uuid.uuid4())); docs.append(c)
            metas.append({"doc_id": doc_id, "file": filename, "page": page})
    for i in range(0, len(ids), 100):
        col.add(ids=ids[i:i+100], documents=docs[i:i+100], metadatas=metas[i:i+100])
    return len(ids)

def delete_file(user_id, doc_id):
    _col(user_id).delete(where={"doc_id": doc_id})

def answer(user_id, question, k=5):
    col = _col(user_id)
    if col.count() == 0:
        return "Please upload some notes first, then ask me questions.", []
    res = col.query(query_texts=[question], n_results=min(k, col.count()))
    docs, metas = res["documents"][0], res["metadatas"][0]
    context = "\n\n".join(f"[{i+1}] ({m['file']} {m['page']})\n{d}"
                          for i, (d, m) in enumerate(zip(docs, metas)))
    msg = llm.messages.create(
        model=MODEL, max_tokens=1000,
        system=("You are a study buddy. Answer the student's question using ONLY the "
                "notes excerpts provided. Cite sources like [1]. If the notes don't "
                "contain the answer, say so clearly instead of guessing."),
        messages=[{"role": "user", "content": f"Notes:\n{context}\n\nQuestion: {question}"}])
    sources = [{"n": i+1, "file": m["file"], "page": m["page"]} for i, m in enumerate(metas)]
    return msg.content[0].text, sources
