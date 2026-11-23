#!/usr/bin/env bash
# install.sh — instala agent-secrets: el comando `secret` y las reglas para los agentes.
# Idempotente: correrlo de nuevo actualiza sin duplicar. Nunca toca los secretos guardados.
#
#   ./install.sh               instala o actualiza
#   ./install.sh --uninstall   quita enlaces y bloques de reglas
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
CONF="$HOME/.config/agent-secrets"
RULES="$CONF/AGENTS.md"

say() { printf '  %s\n' "$*"; }

# block FILE CONTENT|"" — reemplaza (o quita, si CONTENT es "") el bloque marcado de FILE.
# Respalda FILE solo si cambia.
block() {
  python3 - "$1" "$2" <<'PY'
import re, sys, time
from pathlib import Path
path, content = Path(sys.argv[1]).expanduser(), sys.argv[2]
begin, end = "<!-- agent-secrets:begin -->", "<!-- agent-secrets:end -->"
old = path.read_text() if path.exists() else ""
new = re.sub(r"\n*" + re.escape(begin) + r".*?" + re.escape(end) + r"\n*", "\n\n", old, flags=re.S).strip("\n")
if content:
    new = (new + "\n\n" if new else "") + f"{begin}\n{content.strip()}\n{end}"
new = new + "\n" if new else ""
if new == old:
    print(f"  {path}: sin cambios")
    sys.exit()
if old:
    path.with_name(path.name + f".bak-agent-secrets-{time.strftime('%Y%m%d-%H%M%S')}").write_text(old)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(new) if new else path.unlink()
print(f"  {path}: {'actualizado' if content else 'bloque quitado'}")
PY
}

# claude_perms add|remove — permisos de solo lectura para Claude Code. `set` y `run` quedan fuera a
# propósito: `set --stdin --force` reemplaza un secreto sin intervención humana y `run` ejecuta cualquier comando.
claude_perms() {
  python3 - "$1" <<'PY'
import json, sys, time
from pathlib import Path
path = Path.home() / ".claude" / "settings.json"
rules = ["Bash(secret ls)", "Bash(secret ls *)", "Bash(secret check *)", "Bash(secret help)"]
raw = path.read_text() if path.exists() else "{}"
data = json.loads(raw or "{}")
allow = data.setdefault("permissions", {}).setdefault("allow", [])
before = list(allow)
if sys.argv[1] == "add":
    allow.extend(r for r in rules if r not in allow)
else:
    allow[:] = [r for r in allow if r not in rules]
if allow == before:
    print(f"  {path}: permisos sin cambios")
    sys.exit()
if path.exists():
    path.with_name(path.name + f".bak-agent-secrets-{time.strftime('%Y%m%d-%H%M%S')}").write_text(raw)
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
print(f"  {path}: permisos {'agregados' if sys.argv[1] == 'add' else 'quitados'} (ls, check, help)")
PY
}

unlink_ours() { [ -L "$1" ] && [ "$(readlink "$1")" = "$2" ] && rm "$1" && say "quitado $1"; return 0; }

if [ "${1:-}" = "--uninstall" ]; then
  echo "Desinstalando agent-secrets (los secretos siguen en el llavero)"
  unlink_ours "$BIN/secret" "$ROOT/secret"
  unlink_ours "$RULES" "$ROOT/AGENTS.md"
  [ -f "$HOME/.claude/CLAUDE.md" ] && block "$HOME/.claude/CLAUDE.md" ""
  [ -f "$HOME/.claude/settings.json" ] && claude_perms remove
  [ -f "$HOME/.codex/AGENTS.md" ] && block "$HOME/.codex/AGENTS.md" ""
  exit 0
fi

echo "Dependencias"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "  falta Python >= 3.9"; exit 1; }
if [ "$(uname)" = "Darwin" ]; then
  say "macOS: Keychain (security) y diálogos (osascript) vienen con el sistema"
else
  command -v secret-tool >/dev/null || { say "falta secret-tool: sudo apt install libsecret-tools"; exit 1; }
  command -v zenity >/dev/null || say "aviso: sin zenity no hay diálogo gráfico (solo terminal o --stdin)"
fi

echo "Comando y reglas"
mkdir -p "$BIN" "$CONF"
if [ -e "$BIN/secret" ] && [ "$(readlink "$BIN/secret" 2>/dev/null)" != "$ROOT/secret" ]; then
  say "$BIN/secret ya existe y no es de agent-secrets: no se toca"; exit 1
fi
chmod +x "$ROOT/secret"
ln -sfn "$ROOT/secret" "$BIN/secret" && say "$BIN/secret -> $ROOT/secret"
ln -sfn "$ROOT/AGENTS.md" "$RULES" && say "$RULES -> $ROOT/AGENTS.md"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) say "aviso: $BIN no está en el PATH; agrega a tu shell: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

echo "Agentes"
# Claude Code: importa el archivo (un git pull del repo actualiza las reglas).
if [ -d "$HOME/.claude" ]; then
  block "$HOME/.claude/CLAUDE.md" "@~/.config/agent-secrets/AGENTS.md"
  claude_perms add
else
  say "Claude Code no encontrado (~/.claude): omitido"
fi
# Codex: AGENTS.md global no admite imports, así que se copia el texto (correr install.sh tras un git pull).
if [ -d "$HOME/.codex" ]; then
  block "$HOME/.codex/AGENTS.md" "$(cat "$ROOT/AGENTS.md")"
else
  say "Codex no encontrado (~/.codex): omitido"
fi

echo "Verificación"
"$ROOT/secret" ls >/dev/null && say "el llavero responde"
echo "Listo. Las sesiones nuevas de los agentes ya cargan las reglas."
