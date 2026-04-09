"""
Semantic Scholar API client for fetching paper metadata and abstracts.

Uses the Semantic Scholar Academic Graph API (free, no auth for basic usage).
Rate limit: 100 requests per 5 minutes for unauthenticated access.
"""

import json
import time
from typing import Any

import httpx


BASE_URL = "https://api.semanticscholar.org/graph/v1"
FIELDS = "title,authors,year,venue,abstract,citationCount,externalIds"
REQUEST_INTERVAL = 3.0


def fetch_reference(query: str, client: httpx.Client | None = None) -> dict[str, Any]:
    """
    Search Semantic Scholar for a paper by title or citation key.

    Parameters
    ----------
    query : str
        Paper title or citation key to search for.
    client : httpx.Client | None
        Optional reusable HTTP client. Creates one if not provided.

    Returns
    -------
    dict[str, Any]
        Paper metadata with keys: title, authors, year, venue, abstract,
        citation_count, semantic_scholar_id, found.
        If not found, returns dict with found=False and the query.
    """
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=15.0)

    try:
        resp = client.get(
            f"{BASE_URL}/paper/search",
            params={"query": query, "limit": 1, "fields": FIELDS},
        )

        if resp.status_code == 429:
            time.sleep(10)
            resp = client.get(
                f"{BASE_URL}/paper/search",
                params={"query": query, "limit": 1, "fields": FIELDS},
            )

        if resp.status_code != 200:
            return {"found": False, "query": query, "error": f"HTTP {resp.status_code}"}

        data = resp.json()
        papers = data.get("data", [])
        if not papers:
            return {"found": False, "query": query, "error": "No results"}

        paper = papers[0]
        authors = [
            a.get("name", "Unknown") for a in (paper.get("authors") or [])
        ]

        return {
            "found": True,
            "query": query,
            "title": paper.get("title", ""),
            "authors": authors,
            "year": paper.get("year"),
            "venue": paper.get("venue", ""),
            "abstract": paper.get("abstract", ""),
            "citation_count": paper.get("citationCount", 0),
            "semantic_scholar_id": paper.get("paperId", ""),
            "external_ids": paper.get("externalIds", {}),
        }
    finally:
        if own_client:
            client.close()


def fetch_references_batch(queries: list[str]) -> list[dict[str, Any]]:
    """
    Fetch multiple papers from Semantic Scholar with rate limiting.

    Parameters
    ----------
    queries : list[str]
        List of paper titles or citation keys.

    Returns
    -------
    list[dict[str, Any]]
        List of paper metadata dicts (same format as fetch_reference).
    """
    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=15.0) as client:
        for i, query in enumerate(queries):
            if i > 0:
                time.sleep(REQUEST_INTERVAL)
            result = fetch_reference(query, client=client)
            results.append(result)
            status = "found" if result["found"] else "not found"
            print(f"[{i + 1}/{len(queries)}] {query[:60]}... → {status}")
    return results


def fetch_and_print(query: str) -> None:
    """
    Fetch a single reference and print structured output.

    This is the entry point called by the fetch-references.ts tool.
    """
    result = fetch_reference(query)
    print(json.dumps(result, indent=2, ensure_ascii=False))
