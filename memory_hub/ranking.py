"""Deterministic BM25 candidate ranking; lifecycle validation belongs to recall."""
from collections import Counter
import math
import re
import unicodedata

# Question scaffolding must not make an unrelated note look like evidence.
STOP = frozenset("a an and are as at be been being but by can could did do does for from had has have how i if in into is it its me my of on or our should so that the their them there these they this those to was we were what when where which who why will with would you your".split())


def terms(text):
    return [t for t in re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold()) if t not in STOP]


def document(row):
    m = row["meta"]
    aliases = m.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    if not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases):
        aliases = []
    return (terms(str(m.get("title", ""))) * 3 + terms(row["body"])
            + terms(str(m.get("key", ""))) + terms(" ".join(aliases)))


def bm25(rows, query):
    """Map paths to scores. Require meaningful overlap, not an arbitrary raw score.

    BM25 scores vary with corpus size. Query coverage is a separate gate: at least
    one meaningful term and at least half of the query vocabulary must match.
    Exact keys are selected independently by recall, ahead of ranked matches.
    """
    query_terms = set(terms(query))
    docs = [Counter(document(row)) for row in rows]
    if not docs or not query_terms:
        return {}
    frequency = Counter(t for doc in docs for t in doc)
    average = sum(sum(d.values()) for d in docs) / len(docs) or 1
    scores = {}
    for row, doc in zip(rows, docs):
        matched = query_terms & doc.keys()
        if not matched or len(matched) / len(query_terms) < .5:
            continue
        norm = 1.2 * (0.25 + 0.75 * sum(doc.values()) / average)
        score = sum(math.log(1 + (len(docs) - frequency[t] + .5) / (frequency[t] + .5))
                    * doc[t] * 2.2 / (doc[t] + norm) for t in matched)
        scores[row["path"]] = score
    return scores
