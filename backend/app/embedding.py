from __future__ import annotations

import os
from functools import lru_cache
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer


EMBEDDING_MODEL_ID = os.getenv("EMBEDDING_MODEL_ID") or "sentence-transformers/all-mpnet-base-v2"  # 768-dim


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL_ID)


def embed_texts(texts: List[str]) -> np.ndarray:
    model = get_model()
    return np.asarray(model.encode(texts, normalize_embeddings=True, convert_to_numpy=True))
