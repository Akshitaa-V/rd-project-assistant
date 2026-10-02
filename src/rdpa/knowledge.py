"""Knowledge base over project documents with BM25 ranking.

Kept dependency-free on purpose: it runs anywhere, ranks well on short
technical documents and every answer can cite the document it came from.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import config

STOPWORDS = set("""a an and are as at be by did do does for from has have how in is it its
of on or the that this to was were what when where which who why will with after about
we our they their there than then into up down out""".split())


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text.lower())
    out = []
    for t in tokens:
        if t in STOPWORDS:
            continue
        for suffix in ("ing", "ed", "es", "s"):
            if len(t) > 4 and t.endswith(suffix):
                t = t[: -len(suffix)]
                break
        out.append(t)
    return out


@dataclass
class Hit:
    doc_id: str
    title: str
    score: float
    snippet: str


class KnowledgeBase:
    def __init__(self, docs_dir: Path = config.DOCS_DIR, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: dict[str, tuple[str, str]] = {}
        for path in sorted(docs_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = text.splitlines()[0].lstrip("# ").strip()
            self.docs[path.stem] = (title, text)
        self.tf = {d: Counter(tokenize(t + " " + t.split("\n", 1)[0])) for d, (_, t) in self.docs.items()}
        self.len = {d: sum(c.values()) for d, c in self.tf.items()}
        self.avg_len = sum(self.len.values()) / max(1, len(self.len))
        df = Counter(term for c in self.tf.values() for term in c)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 3) -> list[Hit]:
        terms = tokenize(query)
        scores = {}
        for d, tf in self.tf.items():
            s = 0.0
            for t in terms:
                f = tf.get(t)
                if not f:
                    continue
                norm = f + self.k1 * (1 - self.b + self.b * self.len[d] / self.avg_len)
                s += self.idf[t] * f * (self.k1 + 1) / norm
            if s > 0:
                scores[d] = s
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        return [Hit(d, self.docs[d][0], round(s, 3), self._snippet(d, terms)) for d, s in ranked]

    def _snippet(self, doc_id: str, terms: list[str]) -> str:
        body = self.docs[doc_id][1].split("\n", 2)[-1].strip()
        sentences = re.split(r"(?<=\.)\s+", body)
        scores = [sum(t in tokenize(s) for t in terms) for s in sentences]
        i = max(range(len(sentences)), key=lambda j: (scores[j], -j))
        # pair the best sentence with its strongest neighbour: a finding and its decision
        # usually sit in consecutive sentences
        j = max((n for n in (i - 1, i + 1) if 0 <= n < len(sentences)),
                key=lambda n: (scores[n], -n), default=None)
        picked = sorted({i, j} - {None})
        return " ".join(sentences[k].strip() for k in picked)

    def get(self, doc_id: str) -> str | None:
        doc = self.docs.get(doc_id)
        return doc[1] if doc else None
