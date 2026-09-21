"""Orquestación de páginas, catálogo y métricas sin lógica HTTP."""

from alert_store import percentage
from browse_repository import BrowseRepository
from browsing_config import SETTINGS
from page_cursor import CursorCodec
from service_catalog import add_service_monitoring_context, annotate_sensitive_alerts
from store_factory import open_store


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
            source = repo.source()
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
            scope, params, _ = repo.event_scope(query, source, sensitive)
            rows, page = repo.services(query, scope, params, self.codec("services", source, query))
            summary = repo.summary(scope, params)
            top_query = query.model_copy(
                update={
                    "cursor": None,
                    "page_size": SETTINGS.top_services,
                    "sort": "volume",
                }
            )
            top = []
            if with_summary:
                top, _ = repo.services(
                    top_query, scope, params, self.codec("services", source, top_query)
                )
            identifiers = list({row["relying_party"] for row in [*rows, *top]})
            open_alerts = repo.open_alerts(source, identifiers)
            revision = repo.revision(source)
        maximum = int(top[0]["total_events"]) if top else 0
        for collection in (rows, top):
            for item in collection:
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
                item["bar_percent"] = percentage(item["total_events"], maximum)
            add_service_monitoring_context({"services": collection}, catalog, open_alerts)
        metrics = {
            **summary,
            "services": rows,
            "top_services": top,
            "window_days": query.window_days,
            "latest_event_time": summary["last_seen_utc"],
            "revision": revision,
        }
        add_service_monitoring_context(metrics, catalog, open_alerts)
        return {"data": rows, "page": page, "source": source, "metrics": metrics}

    def revision(self):
        with open_store(self.dashboard.state_db) as store:
            repo = BrowseRepository(store)
            source = repo.source()
            return {"source": source, "revision": repo.revision(source)}
