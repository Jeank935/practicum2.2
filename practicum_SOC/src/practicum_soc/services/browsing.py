"""Orquestación de páginas, catálogo y métricas sin lógica HTTP."""

import hashlib
import json

from practicum_soc.core.cursor import CursorCodec
from practicum_soc.repositories.alerts import percentage
from practicum_soc.repositories.browsing import BrowseRepository
from practicum_soc.repositories.factory import open_store
from practicum_soc.services.catalog import add_service_monitoring_context, annotate_sensitive_alerts


class BrowseService:
    def __init__(self, dashboard, secret):
        self.dashboard = dashboard
        self.secret = secret

    def codec(self, kind, source, query):
        return CursorCodec(
            self.secret,
            {
                "kind": kind,
                "source": source,
                "query": query.model_dump(mode="json", exclude={"cursor"}),
            },
        )

    def alerts(self, query):
        with open_store(self.dashboard.state_db) as store:
            repo = BrowseRepository(store)
            source = query.source or repo.source()
            rows, page = repo.alerts(query, source, self.codec("alerts", source, query))
        annotate_sensitive_alerts(rows, self.dashboard._service_catalog())
        return {"data": rows, "page": page, "source": source}

    def services(self, query, *, with_summary=False):
        catalog = self.dashboard._service_catalog()
        sensitive = [
            key
            for key, value in catalog["sensitivity"].items()
            if value.get("level") in {"high", "medium"}
        ]
        with open_store(self.dashboard.state_db) as store:
            repo = BrowseRepository(store)
            source = repo.source()
            revision = repo.revision(source)
            codec = self.codec("services", source, query)
            if query.cursor:
                codec.decode(query.cursor, len(repo.service_keys(query.sort)))
            cache_key = json.dumps(
                {
                    "revision": revision,
                    "query": query.model_dump(mode="json"),
                    "summary": with_summary,
                    "catalog": self.dashboard.catalog_revision(),
                    "signing_key": hashlib.sha256(codec.key).hexdigest(),
                },
                sort_keys=True,
            )
            cached = self.dashboard.service_pages.get(cache_key)
            if cached is not None:
                return cached
            scope, params, _ = repo.event_scope(query, source, sensitive)
            rows, page = repo.services(query, scope, params, codec)
            summary = repo.summary(scope, params)
            identifiers = [row["relying_party"] for row in rows]
            open_alerts = repo.open_alerts(source, identifiers)
        for item in rows:
            for field in (
                "total_events",
                "success_count",
                "failure_count",
                "lockout_count",
                "distinct_users",
                "distinct_client_ips",
            ):
                item[field] = int(item[field] or 0)
            item["adverse_rate"] = percentage(
                item["failure_count"] + item["lockout_count"], item["total_events"]
            )
            item["share_percent"] = percentage(item["total_events"], summary["total_events"])
            # Una escala global conserva la comparación entre páginas y filtros.
            item["bar_percent"] = item["share_percent"]
        metrics = {
            **summary,
            "services": rows,
            "top_services": rows if with_summary else [],
            "window_days": query.window_days,
            "latest_event_time": summary["last_seen_utc"],
            "revision": revision,
        }
        add_service_monitoring_context(metrics, catalog, open_alerts)
        result = {"data": rows, "page": page, "source": source, "metrics": metrics}
        self.dashboard.service_pages.put(cache_key, result)
        return result

    def revision(self):
        with open_store(self.dashboard.state_db) as store:
            repo = BrowseRepository(store)
            source = repo.source()
            return {"source": source, "revision": repo.revision(source)}
