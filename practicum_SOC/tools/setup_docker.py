"""Genera secretos locales de Compose sin sobrescribir configuración existente."""

from pathlib import Path
from secrets import token_hex


def main() -> None:
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


if __name__ == "__main__":
    main()
