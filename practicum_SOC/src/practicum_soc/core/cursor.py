"""Cursores firmados, ligados a la fuente, filtros, tamaño y orden."""

import base64
import hashlib
import hmac
import json


class InvalidCursor(ValueError):
    pass


class CursorCodec:
    def __init__(self, secret: str, context: dict):
        if not secret:
            raise RuntimeError("Falta configurar la clave de cursores")
        self.key = hmac.digest(secret.encode(), b"soc-pagination-v1", "sha256")
        self.context = hashlib.sha256(
            json.dumps(context, sort_keys=True, default=str).encode()
        ).hexdigest()

    def encode(self, anchor: list, direction: str, page: int) -> str:
        raw = json.dumps(
            {"v": 1, "ctx": self.context, "anchor": anchor, "direction": direction, "page": page},
            separators=(",", ":"),
        ).encode()
        signature = hmac.digest(self.key, raw, "sha256")
        return base64.urlsafe_b64encode(signature + raw).decode().rstrip("=")

    def decode(self, token: str, key_count: int):
        try:
            packed = base64.b64decode(
                token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
            )
            signature, raw = packed[:32], packed[32:]
            if not hmac.compare_digest(signature, hmac.digest(self.key, raw, "sha256")):
                raise ValueError()
            value = json.loads(raw)
            if (
                value["v"] != 1
                or value["ctx"] != self.context
                or value["direction"] not in {"next", "previous"}
                or type(value["page"]) is not int
                or value["page"] < 1
                or not isinstance(value["anchor"], list)
                or len(value["anchor"]) != key_count
                or any(type(item) not in {str, int} for item in value["anchor"])
            ):
                raise ValueError()
            return value
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise InvalidCursor(
                "Cursor inválido o incompatible con estos filtros. Vuelve a la primera página."
            ) from None


def keyset_page(db, sql: str, params: list, keys: tuple, descending: bool, query, codec):
    cursor = codec.decode(query.cursor, len(keys)) if query.cursor else None
    backwards = cursor is not None and cursor["direction"] == "previous"
    comparator = "<" if descending != backwards else ">"
    key_sql = ", ".join(keys)
    if cursor:
        sql += f" AND ({key_sql}) {comparator} ({', '.join('?' for _ in keys)})"
        params = [*params, *cursor["anchor"]]
    direction = "DESC" if descending != backwards else "ASC"
    sql += " ORDER BY " + ", ".join(f"{key} {direction}" for key in keys) + " LIMIT ?"
    rows = [dict(row) for row in db.execute(sql, (*params, query.page_size + 1)).fetchall()]
    has_more = len(rows) > query.page_size
    rows = rows[: query.page_size]
    if backwards:
        rows.reverse()
    page = cursor["page"] if cursor else 1
    has_previous = has_more if backwards else cursor is not None
    has_next = cursor is not None if backwards else has_more

    def anchor(row):
        return [
            int(row[key]) if key in {"total_events", "failure_count", "risk_score"} else row[key]
            for key in keys
        ]

    return rows, {
        "page_size": query.page_size,
        "page": page,
        "has_next": bool(rows) and has_next,
        "has_previous": bool(rows) and has_previous,
        "next_cursor": codec.encode(anchor(rows[-1]), "next", page + 1)
        if rows and has_next
        else None,
        "previous_cursor": codec.encode(anchor(rows[0]), "previous", max(1, page - 1))
        if rows and has_previous
        else None,
    }
