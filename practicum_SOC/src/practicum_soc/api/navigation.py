"""URLs de navegación y retorno interno seguro, sin acceso a la base."""

from urllib.parse import urlencode, urlsplit


def query_url(path, query, **changes):
    data = query.model_dump(mode="json")
    data.update(changes)
    return (
        path
        + "?"
        + urlencode(
            {
                key: str(value).lower() if isinstance(value, bool) else value
                for key, value in data.items()
                if value is not None
            }
        )
    )


def navigation(path, query, page):
    return {
        "first_url": query_url(path, query, cursor=None),
        "previous_url": query_url(path, query, cursor=page["previous_cursor"])
        if page["has_previous"]
        else None,
        "next_url": query_url(path, query, cursor=page["next_cursor"])
        if page["has_next"]
        else None,
        "return_to": query_url(path, query),
    }


def safe_return_path(value):
    if not value or len(value) > 8192 or any(ch in value for ch in ("\\", "\r", "\n")):
        return "/alerts"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path not in {"/alerts", "/services"}:
        return "/alerts"
    return value
