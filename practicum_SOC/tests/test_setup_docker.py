import pytest

from tools.setup_docker import sync_source_env


def test_sync_source_preserves_soc_secrets_and_quotes_credentials(tmp_path):
    source = tmp_path / "source.env"
    target = tmp_path / "docker.env"
    source.write_text(
        'SOC_DB_DSN="host=db password=p$a\'ss"\n'
        "SOC_DB_VIEW=integration.logs\nSOC_PSEUDONYM_KEY=unwanted\n",
        encoding="utf-8",
    )
    target.write_text(
        "SOC_DB_DSN=\nSOC_DB_VIEW=\nSOC_PSEUDONYM_KEY='keep'\nSOC_OIDC_CLIENT_SECRET='also-keep'\n",
        encoding="utf-8",
    )
    sync_source_env(target, source)
    result = target.read_text(encoding="utf-8")
    assert "SOC_DB_DSN='host=db password=p$a\\'ss'" in result
    assert "SOC_DB_VIEW='integration.logs'" in result
    assert "SOC_PSEUDONYM_KEY='keep'" in result
    assert "SOC_OIDC_CLIENT_SECRET='also-keep'" in result
    assert "unwanted" not in result


def test_sync_source_rejects_incomplete_configuration_without_writing(tmp_path):
    source = tmp_path / "source.env"
    target = tmp_path / "docker.env"
    source.write_text("SOC_DB_VIEW=integration.logs\n", encoding="utf-8")
    target.write_text("SOC_PSEUDONYM_KEY='keep'\n", encoding="utf-8")
    before = target.read_bytes()
    with pytest.raises(ValueError, match="SOC_DB_DSN"):
        sync_source_env(target, source)
    assert target.read_bytes() == before
