from concurrent.futures import ThreadPoolExecutor

from practicum_soc.core.auth_config import AuthSettings
from practicum_soc.core.rate_limits import consume
from practicum_soc.repositories.alerts import AlertStore


def test_persistent_windows_scope_isolation_and_expired_cleanup(tmp_path):
    path = tmp_path / "limits.db"
    policy = AuthSettings.from_env().policy
    policy["rate_limits"]["demo"] = {"requests": 1, "window_seconds": 60}
    with AlertStore(path) as store:
        assert consume(store, "demo", "alice", policy, now=120) == 0
    with AlertStore(path) as store:
        assert consume(store, "demo", "alice", policy, now=121) == 59
        assert consume(store, "demo", "bob", policy, now=121) == 0
        assert consume(store, "report", "alice", policy, now=121) == 0
        assert consume(store, "demo", "alice", policy, now=180) == 0
        assert (
            store.connection.execute("SELECT COUNT(*) AS n FROM platform_rate_limits").fetchone()[
                "n"
            ]
            == 1
        )
        assert "alice" not in str(
            store.connection.execute("SELECT * FROM platform_rate_limits").fetchall()
        )


def test_atomic_limit_with_simultaneous_requests(tmp_path):
    path = tmp_path / "concurrent.db"
    policy = AuthSettings.from_env().policy
    policy["rate_limits"]["case_update"] = {"requests": 5, "window_seconds": 60}
    with AlertStore(path):
        pass

    def attempt(_):
        with AlertStore(path) as store:
            return consume(store, "case_update", "same-user", policy, now=120)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(attempt, range(12)))
    assert results.count(0) == 5
    assert results.count(60) == 7
