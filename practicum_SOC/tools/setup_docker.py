"""Genera secretos locales de Compose sin sobrescribir configuración existente."""

import argparse
from pathlib import Path
from secrets import token_hex

SOURCE_KEYS = frozenset(
    {
        "SOC_DB_DSN",
        "SOC_DB_VIEW",
        "SOC_DB_TIME_COLUMN",
        "SOC_DB_ID_COLUMN",
        "SOC_DB_CONNECT_TIMEOUT_SECONDS",
        "SOC_DB_STATEMENT_TIMEOUT_SECONDS",
        "SOC_DB_RETRY_ATTEMPTS",
        "SOC_DB_RETRY_DELAY_SECONDS",
    }
)


def sync_source_env(target: Path, source: Path) -> None:
    """Copia únicamente la configuración del origen; conserva secretos del SOC."""
    values = {}
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if name not in SOURCE_KEYS:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            values[name] = value
    if not values.get("SOC_DB_DSN") or not values.get("SOC_DB_VIEW"):
        raise ValueError("El archivo de origen necesita SOC_DB_DSN y SOC_DB_VIEW.")
    # Comillas simples impiden que Compose expanda dólares de las credenciales.
    replacements = {
        name: name + "='" + value.replace("'", "\\'") + "'" for name, value in values.items()
    }
    lines = []
    for line in target.read_text(encoding="utf-8").splitlines():
        name = line.split("=", 1)[0].strip()
        lines.append(replacements.pop(name, line))
    lines.extend(replacements.values())
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-env", type=Path, help="Copiar origen UTPL desde este archivo local"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / ".env.docker"
    key_file = root / ".secrets/pseudonym_key.txt"
    key = key_file.read_text(encoding="utf-8").strip() if key_file.is_file() else token_hex(32)
    if not key or any(character in key for character in "\r\n'$"):
        raise SystemExit("La clave HMAC necesita configuración manual segura para Compose.")
    replacements = {
        "SOC_POSTGRES_PASSWORD": token_hex(32),
        "SOC_APP_PASSWORD": token_hex(32),
        "SOC_GRAFANA_PASSWORD": token_hex(32),
        "GRAFANA_ADMIN_PASSWORD": token_hex(32),
        "SOC_PSEUDONYM_KEY": key,
        "SOC_OIDC_CLIENT_SECRET": token_hex(32),
        "SOC_IDP_DB_PASSWORD": token_hex(32),
        "SOC_IDP_ADMIN_PASSWORD": token_hex(32),
        "SOC_BOOTSTRAP_ADMIN_PASSWORD": token_hex(24),
        "SOC_BOOTSTRAP_ANALYST_PASSWORD": token_hex(24),
    }
    template = (root / ".env.docker.example").read_text(encoding="utf-8")
    for name, value in replacements.items():
        template = template.replace(f"{name}=\n", f"{name}='{value}'\n")
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        names = {line.split("=", 1)[0].strip() for line in existing.splitlines() if "=" in line}
        additions = [
            f"{name}='{value}'" for name, value in replacements.items() if name not in names
        ]
        if additions:
            with target.open("a", encoding="utf-8") as handle:
                handle.write("\n# OIDC local: secretos añadidos sin cambiar los existentes.\n")
                handle.write("\n".join(additions) + "\n")
        print("Configuración conservada; se añadieron únicamente variables secretas faltantes.")
    else:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(template)
        print("Creado .env.docker. No se muestran secretos; no lo comparta ni versione.")
    if args.source_env:
        sync_source_env(target, args.source_env)
        print("Origen institucional configurado en .env.docker; secretos del SOC conservados.")


if __name__ == "__main__":
    main()
