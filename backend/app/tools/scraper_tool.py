"""
Ricerca online / chiamate ad API esterne per raccogliere informazioni.
"""
import requests


def web_search(query: str, timeout: int = 10) -> dict:
    """
    Esegue una ricerca online semplice. In produzione, sostituire con una vera
    API di ricerca (es. Bing, SerpAPI, Google Custom Search) usando una API key
    configurata in app.core.config.settings.
    """
    try:
        response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            timeout=timeout,
            headers={"User-Agent": "CortexEnterpriseAgent/1.0"},
        )
        response.raise_for_status()
        return {"query": query, "status_code": response.status_code, "raw_html": response.text[:2000]}
    except requests.RequestException as exc:
        return {"query": query, "error": str(exc)}
