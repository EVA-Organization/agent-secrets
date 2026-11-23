# agent-secrets

Estándar para que los agentes de código (Claude Code, Codex, los que vengan) **guarden y usen
secretos sin verlos**. Los valores viven en el llavero del sistema; el agente solo maneja nombres.

- **Almacén:** Keychain en macOS, Secret Service (gnome-keyring, KWallet) en Linux. Sin archivos en
  texto plano, sin servidor, sin puerto abierto.
- **Un comando, `secret`**, sin verbo para leer un valor: los secretos se inyectan en el entorno de un
  proceso (`run`, con la salida redactada) o se escriben en un archivo 0600 (`render`).
- **Reglas para los agentes** en [`AGENTS.md`](AGENTS.md), cargadas en la configuración global de cada uno.

## Instalar

```bash
git clone git@github.com:EVA-Organization/agent-secrets.git ~/Repositorios/EVA/agent-secrets
cd ~/Repositorios/EVA/agent-secrets && ./install.sh
```

Requisitos: Python ≥ 3.9. En Linux, `sudo apt install libsecret-tools` (y `zenity` para el diálogo).
En macOS no hace falta nada más.

El instalador enlaza `~/.local/bin/secret` y `~/.config/agent-secrets/AGENTS.md`, y agrega un bloque
marcado `<!-- agent-secrets -->` a:

| Agente | Archivo | Cómo |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `@~/.config/agent-secrets/AGENTS.md` (se actualiza con `git pull`) |
| Claude Code | `~/.claude/settings.json` | permite sin preguntar `secret ls`, `check` y `help`; `set` y `run` siguen pidiendo permiso |
| Codex | `~/.codex/AGENTS.md` | copia del texto (volver a correr `./install.sh` tras un `git pull`) |
| Otro | — | decirle «corre `secret help`» |

Es idempotente y respalda cada archivo antes de cambiarlo. `./install.sh --uninstall` lo revierte sin
tocar los secretos.

## Instalación por un agente

Si eres un agente (Claude Code, Codex…) y el usuario te pidió instalar esto, sigue estos pasos en orden.
Nunca le pidas un secreto por el chat.

1. **Dependencias.** Comprueba `python3 --version` (≥ 3.9).
   - Linux: si falta `secret-tool` o `zenity`, **pídele al usuario** que corra
     `sudo apt install libsecret-tools zenity` (tú no tienes su contraseña).
   - macOS: no hace falta nada más. Si `python3` no existe, pídele `xcode-select --install`.
2. **Clonar:** `gh repo clone EVA-Organization/agent-secrets ~/Repositorios/EVA/agent-secrets`.
3. **Instalar:** `cd ~/Repositorios/EVA/agent-secrets && ./install.sh`. Si avisa que `~/.local/bin` no está en el
   `PATH`, dile al usuario qué línea agregar a su `~/.bashrc` o `~/.zshrc` (no la edites sin permiso) y usa la ruta
   completa `~/.local/bin/secret` mientras tanto.
4. **Comprobar** con un secreto desechable; ningún paso debe imprimir el valor:
   ```bash
   python3 -m unittest test_secret.py                       # todas en OK
   python3 -c 'import secrets;print("prueba-"+secrets.token_hex(12))' | secret set test/install/demo --stdin
   secret ls test/                                          # muestra test/install/demo
   secret check test/install/demo                           # presente · 31 caracteres · huella …
   secret run -e V=test/install/demo -- sh -c 'echo "$V"; printf %s "$V" | base64'
                                                            # dos líneas [secret://test/install/demo]
   secret rm test/install/demo                              # el usuario confirma en un diálogo
   ```
5. **Reportar** al usuario qué se instaló y que las sesiones **nuevas** ya cargan las reglas (la actual no).
   Los secretos no viajan entre máquinas: se cargan con `secret set` en cada una.

## Usar

```bash
secret set eva/elevenlabs/api-key --why "TTS del video"   # diálogo para pegar el valor
<cmd> | secret set eva/x/token --stdin                    # cuando lo genera un programa
secret ls [eva/]                                          # nombres
secret check eva/elevenlabs/api-key                       # existe · largo · huella
secret run -e XI_API_KEY=eva/elevenlabs/api-key -- python tts.py
secret run --env-file .env.tpl -- docker compose up       # .env.tpl: VAR=secret://nombre
secret render config.tpl ./config.json                    # {{secret:nombre}} → archivo 0600
secret rm eva/x/token                                     # pide confirmación en pantalla
```

Nombres: `<ámbito>/<servicio>/<clave>` en minúsculas. `secret://<nombre>` es una referencia, no un secreto.

## Límites

- Es una barrera contra **fugas accidentales**, no un sandbox. Un proceso que corre como tu usuario
  puede leer el llavero desbloqueado, y un comando dentro de `secret run` recibe el valor real.
- La redacción cubre el valor y sus codificaciones comunes (base64, hex, URL, JSON) dentro de una
  línea. Una transformación que lo parta o altere (`xxd -p`, `rev`) no se redacta.
- No dar permiso automático a `secret run` (ejecuta cualquier comando) ni a `secret set` (con `--stdin --force`
  reemplaza un secreto sin intervención humana) en ningún agente.
- El llavero no es un respaldo: si se pierde, los tokens se reemiten en su proveedor.
- Sin sesión gráfica ni llavero (SSH, servidores) el comando falla; no cae a texto plano.

## Pruebas

```bash
python3 -m unittest -v test_secret.py
```

## Licencia

MIT. Algunas ideas (huella con KDF, codificaciones a redactar, destinos prohibidos para `render`)
vienen de [`arik-web/agentic-secrets`](https://github.com/arik-web/agentic-secrets), de dominio público.
