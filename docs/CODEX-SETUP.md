# Conectar Codex con Claude Code en remisionesjuicio

Este proyecto está preparado para que Claude Code actúe como coordinador y Codex como segundo ingeniero. `CLAUDE.md` contiene las invariantes del proyecto y `AGENTS.md` las instrucciones específicas para Codex.

## Requisitos locales

- Claude Code instalado y autenticado.
- Node.js 18.18 o superior.
- Codex CLI instalado y autenticado con ChatGPT o una API key.

## Instalación recomendada — alcance de proyecto

Desde una terminal ubicada en la raíz de `remisionesjuicio`, ejecutar:

```bash
claude plugin marketplace add openai/codex-plugin-cc
claude plugin install codex@openai-codex --scope project
claude plugin enable codex@openai-codex --scope project
```

Después abrir Claude Code en este repositorio y ejecutar:

```text
/codex:setup
/codex:status
```

Si `/codex:setup` informa que Codex CLI no está instalado:

```bash
npm install -g @openai/codex
```

Luego, si hace falta autenticación:

```bash
codex login
```

En Windows, si Codex presenta problemas generales de instalación, inicio, conectividad o rendimiento, también puede utilizarse:

```bash
codex doctor
```

## Si aparece `Unknown skill: codex:setup`

Existe un problema conocido de Claude Code en el que el plugin puede descargarse pero no quedar activado en `enabledPlugins`.

Primero ejecutar:

```bash
claude plugin enable codex@openai-codex --scope project
```

Cerrar y volver a abrir Claude Code dentro del repositorio y probar nuevamente:

```text
/codex:setup
```

Si continúa igual, revisar `.claude/settings.json` del proyecto o `~/.claude/settings.json` del usuario y confirmar que exista:

```json
{
  "enabledPlugins": {
    "codex@openai-codex": true
  }
}
```

No colocar tokens, API keys ni credenciales dentro del repositorio.

## Prueba mínima de integración

Una vez que `/codex:setup` indique que todo está correcto:

```text
/codex:review --background
/codex:status
/codex:result
```

Si Codex devuelve una revisión del checkout actual, la conexión funciona.

## Primer trabajo conjunto en este proyecto

Luego pedirle a Claude Code:

```text
Leé CLAUDE.md, AGENTS.md y docs/ARQUITECTURA.md. Confirmá que Codex está disponible con /codex:status. Después delegale a Codex una revisión independiente de la arquitectura y de las invariantes críticas del proyecto, sin modificar archivos. Mientras Codex trabaja, hacé tu propia revisión. Al finalizar, recuperá el resultado, compará ambos análisis y proponé las correcciones concretas que realmente correspondan. A partir de ahora usá Codex como segundo ingeniero en cada hito relevante y evitá que ambos editen simultáneamente los mismos archivos.
```

## Comandos útiles

```text
/codex:review --background
/codex:adversarial-review --background
/codex:rescue --background <tarea>
/codex:status
/codex:result
/codex:cancel
```

La integración usa el Codex CLI local y el mismo checkout local que Claude Code. `AGENTS.md` es la guía de trabajo que Codex debe seguir dentro de este repositorio.
