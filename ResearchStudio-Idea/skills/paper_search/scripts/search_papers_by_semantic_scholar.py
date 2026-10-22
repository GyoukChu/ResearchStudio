#!/usr/bin/env python3
"""Search for academic papers using the Semantic Scholar API."""

import argparse
import os
import tempfile
import time

from _http_runtime import create_session, request

# S2's key tier is 1 request/s CUMULATIVE per key (keyless ~100 / 5 min). paper-search runs each source
# in its own worker process and callers overlap, so pacing must be machine-wide: serialize on a lockfile
# in the system temp dir (shared with idea-spark's scripts/s2_throttle.py) and hold the exclusive lock
# across the sleep, as the arXiv connector does. SEMANTICSCHOLAR_MIN_INTERVAL overrides the keyed 1.1 s.
_THROTTLE_FILE = os.path.join(tempfile.gettempdir(), "semanticscholar_throttle.lock")


def _throttle(keyed: bool) -> None:
    """Block until the interval has elapsed since the last S2 request fired on this machine."""
    wait_for = float(os.environ.get("SEMANTICSCHOLAR_MIN_INTERVAL", "1.1")) if keyed else 3.0
    try:
        import fcntl
    except ImportError:
        time.sleep(wait_for)
        return
    fd = os.open(_THROTTLE_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        raw = os.read(fd, 64).decode("utf-8").strip()
        try:
            last = float(raw) if raw else 0.0
        except ValueError:
            last = 0.0
        wait = wait_for - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, str(time.time()).encode("utf-8"))
    finally:
        os.close(fd)  # releasing the fd also releases the flock


def search_papers_by_semantic_scholar(
    query: str,
    start_year: int,
    end_year: int,
    max_results: int = 10,
) -> list[dict]:
    """Search for papers on Semantic Scholar.

    Args:
        query: Search query string.
        start_year: Filter papers published from this year.
        end_year: Filter papers published up to this year.
        max_results: Maximum number of papers to return.

    Returns:
        List of paper dictionaries.
    """
    API_KEY = os.environ.get("SEMANTICSCHOLAR_API_KEY", "")
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    fields = "title,authors,year,abstract,citationCount,url,venue,publicationDate,externalIds"

    papers: list[dict] = []
    offset = 0
    limit = min(100, max_results)  # API max per request is 100
    session = create_session("PaperSearch/1.0")

    while len(papers) < max_results:
        params = {
            "query": query,
            "offset": offset,
            "limit": limit,
            "fields": fields,
            "year": f"{start_year}-{end_year}",
        }
        headers = {"x-api-key": API_KEY} if API_KEY else {}

        response = request(
            session,
            "GET",
            url,
            source="semantic_scholar",
            params=params,
            headers=headers,
            before_attempt=lambda: _throttle(bool(API_KEY)),
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("data"):
            break

        for item in data["data"]:
            authors = [
                a.get("name", "")
                for a in item.get("authors", [])
                if a.get("name")
            ]
            papers.append({
                "title": item.get("title", ""),
                "authors": authors,
                "year": item.get("year"),
                "abstract": item.get("abstract", "") or "",
                "url": item.get("url", ""),
                "venue": item.get("venue", "") or "",
                "citation_count": item.get("citationCount", 0),
                "publication_date": item.get("publicationDate", ""),
                "source": "semantic_scholar",
                "doi": (item.get("externalIds") or {}).get("DOI"),
                "arxiv_id": (item.get("externalIds") or {}).get("ArXiv"),
            })

        offset += limit

        if offset >= data.get("total", 0):
            break

    return papers[:max_results]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search papers on Semantic Scholar")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--start-year", type=int, required=True, help="Start year")
    parser.add_argument("--end-year", type=int, required=True, help="End year")
    parser.add_argument("--max-papers", type=int, default=10, help="Max number of papers (default: 10)")
    args = parser.parse_args()

    papers = search_papers_by_semantic_scholar(args.query, args.start_year, args.end_year, args.max_papers)
    print(papers[0] if papers else "No papers found.")

# python search_papers_by_semantic_scholar.py --query "data efficacy for LM training" --start-year 2024 --end-year 2026 --max-papers 20
