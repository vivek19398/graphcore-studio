"""Local text library with dependency-free BM25 passage retrieval."""
import json
import math
import re
import threading
import uuid
from collections import Counter
from pathlib import Path

TOKEN = re.compile(r"[\w]+", re.UNICODE)
ALLOWED_SUFFIXES = {".txt", ".md", ".csv", ".json"}
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_LIBRARY_BYTES = 10 * 1024 * 1024
MAX_DOCUMENTS = 100


class KnowledgeError(ValueError):
    pass


class LocalKnowledge:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _read(self):
        docs = []
        for path in self.root.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    docs.append(item)
            except (OSError, ValueError):
                continue
        return docs

    def list(self):
        with self.lock:
            return [{"id": d["id"], "name": d["name"], "characters": len(d["text"]),
                     "created": d["created"]} for d in sorted(self._read(), key=lambda d: d["name"].lower())]

    def add(self, name, text):
        if not isinstance(name, str) or not name.strip() or len(name) > 240:
            raise KnowledgeError("Document needs a filename up to 240 characters")
        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise KnowledgeError("Use a .txt, .md, .csv, or .json document")
        if not isinstance(text, str) or not text.strip() or "\x00" in text:
            raise KnowledgeError("Document must contain readable text")
        size = len(text.encode("utf-8"))
        if size > MAX_DOCUMENT_BYTES:
            raise KnowledgeError("Each document must be 1 MiB or smaller")
        import datetime
        with self.lock:
            docs = self._read()
            if len(docs) >= MAX_DOCUMENTS:
                raise KnowledgeError("The local library can hold up to 100 documents")
            if sum(len(d["text"].encode("utf-8")) for d in docs) + size > MAX_LIBRARY_BYTES:
                raise KnowledgeError("The local library is limited to 10 MiB of text")
            ident = uuid.uuid4().hex
            item = {"id": ident, "name": Path(name).name, "text": text,
                    "created": datetime.datetime.now(datetime.timezone.utc).isoformat()}
            path = self.root / (ident + ".json")
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
            return {"id": ident, "name": item["name"], "characters": len(text), "created": item["created"]}

    def remove(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9]{32}", ident):
            raise KnowledgeError("Invalid document ID")
        with self.lock:
            try:
                (self.root / (ident + ".json")).unlink()
            except FileNotFoundError:
                raise KnowledgeError("Document does not exist")

    @staticmethod
    def _chunks(text, size=1100, overlap=140):
        paragraphs = [p.strip() for p in text.splitlines() if p.strip()]
        if not paragraphs:
            paragraphs = [text.strip()]
        chunks, current = [], ""
        for paragraph in paragraphs:
            while len(paragraph) > size:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(paragraph[:size])
                paragraph = paragraph[size-overlap:]
            candidate = (current + "\n\n" + paragraph).strip()
            if current and len(candidate) > size:
                chunks.append(current)
                current = paragraph
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    def search(self, query, top_k=4):
        if not isinstance(query, str) or not query.strip():
            raise KnowledgeError("Retrieval query is empty")
        top_k = min(10, max(1, int(top_k)))
        query_terms = TOKEN.findall(query.lower())
        if not query_terms:
            return {"query": query, "results": []}
        with self.lock:
            docs = self._read()
        passages = []
        for doc in docs:
            for index, chunk in enumerate(self._chunks(doc["text"])):
                terms = TOKEN.findall(chunk.lower())
                if terms:
                    passages.append({"source": doc["name"], "source_id": doc["id"], "chunk": index + 1,
                                     "text": chunk, "terms": terms, "counts": Counter(terms)})
        if not passages:
            return {"query": query, "results": []}
        df = {}
        for p in passages:
            for term in p["counts"]:
                df[term] = df.get(term, 0) + 1
        avg_len = sum(len(p["terms"]) for p in passages) / len(passages)
        scored = []
        for p in passages:
            length = len(p["terms"])
            score = 0.0
            for term in query_terms:
                tf = p["counts"].get(term, 0)
                if tf:
                    idf = math.log(1 + (len(passages) - df[term] + 0.5) / (df[term] + 0.5))
                    score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / avg_len))
            if score > 0:
                scored.append((score, p))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return {"query": query, "results": [{k: p[k] for k in ("source", "source_id", "chunk", "text")} | {"score": round(score, 4)}
                                               for score, p in scored[:top_k]]}
