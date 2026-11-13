import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE_URL = os.environ.get("QUALITY_API_URL", "http://127.0.0.1:8001").rstrip("/")
API_TOKEN = os.environ.get("QUALITY_API_TOKEN", "local-development-token")


class APIError(Exception):
    pass


def api_request(path, method="GET", payload=None, query=None):
    url = f"{API_BASE_URL}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{urlencode(query)}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": API_TOKEN,
        },
    )
    try:
        with urlopen(request, timeout=4) as response:
            if response.status == 204:
                return None
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail", "API request failed")
        except (ValueError, AttributeError):
            detail = "API request failed"
        raise APIError(f"{detail} (HTTP {exc.code})") from exc
    except (URLError, TimeoutError) as exc:
        raise APIError("Không kết nối được FastAPI. Hãy kiểm tra API đang chạy.") from exc
