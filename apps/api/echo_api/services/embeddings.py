"""Embeddings con normalización a dimensión canónica.

pgvector exige dimensión fija por columna. Usamos EMBEDDING_DIM (1536).
Providers con dimensión menor se rellenan con ceros: el zero-padding
preserva exactamente la similitud coseno entre vectores del mismo provider.
"""
import logging

import httpx

from ..models import EMBEDDING_DIM
from .ai_settings import EmbeddingsConfig

log = logging.getLogger("echo.embeddings")


class EmbeddingsError(Exception):
    pass


def _normalize(vector: list[float]) -> list[float]:
    if len(vector) == EMBEDDING_DIM:
        return vector
    if len(vector) > EMBEDDING_DIM:
        return vector[:EMBEDDING_DIM]
    return vector + [0.0] * (EMBEDDING_DIM - len(vector))


async def embed_texts(config: EmbeddingsConfig, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if config.provider == "openai":
        return await _openai_embed(config, texts)
    if config.provider == "ollama":
        return await _ollama_embed(config, texts)
    if config.provider == "fake":
        return [_fake_embed(text) for text in texts]
    raise EmbeddingsError(f"Proveedor de embeddings desconocido: {config.provider}")


async def _openai_embed(config: EmbeddingsConfig, texts: list[str]) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            (config.base_url or "https://api.openai.com/v1").rstrip("/") + "/embeddings",
            headers={"Authorization": f"Bearer {config.api_key}"},
            json={"model": config.model, "input": [t[:8000] for t in texts]},
        )
    if response.status_code >= 400:
        raise EmbeddingsError(f"Embeddings {response.status_code}: {response.text[:200]}")
    data = response.json()
    ordered = sorted(data["data"], key=lambda item: item["index"])
    return [_normalize(item["embedding"]) for item in ordered]


async def _ollama_embed(config: EmbeddingsConfig, texts: list[str]) -> list[list[float]]:
    results = []
    async with httpx.AsyncClient(timeout=120) as client:
        for text in texts:
            response = await client.post(
                (config.base_url or "http://localhost:11434").rstrip("/") + "/api/embeddings",
                json={"model": config.model, "prompt": text[:8000]},
            )
            if response.status_code >= 400:
                raise EmbeddingsError(f"Ollama embeddings {response.status_code}")
            results.append(_normalize(response.json()["embedding"]))
    return results


def _fake_embed(text: str) -> list[float]:
    """Embedding determinístico para tests (bag-of-hashes normalizado)."""
    import hashlib
    import math

    vector = [0.0] * EMBEDDING_DIM
    for word in text.lower().split():
        digest = int(hashlib.md5(word.encode()).hexdigest()[:8], 16)
        vector[digest % EMBEDDING_DIM] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]
