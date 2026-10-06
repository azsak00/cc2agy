# cc2agy

> **Migration tool from Anthropic Claude Code to Google Antigravity.**
> Converts Claude Code commands, skills, subagents, rules, MCP servers, hooks and whole plugins into the files Antigravity reads.

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)]()
[![Platform: Win | Mac | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

- [English documentation](#what-is-cc2agy)
- [Guia em português](#guia-em-português)

---

## What is cc2agy?

Claude Code users build up slash commands, skills, subagents, project instructions (`CLAUDE.md`), MCP servers and hooks, often packaged as plugins. **cc2agy** turns them into native Google Antigravity resources so they can be reused without rewriting them.

Commands become Antigravity **Skills** (`SKILL.md`), not workflows: Antigravity's documentation states that "Workflows are deprecated and will be retired on November 1, 2026" ([Workflows to skills migration](https://antigravity.google/docs/migration/workflows-to-skills/)).

cc2agy is written in pure Python (standard library only). It never overwrites a file unless you pass `--overwrite`, and every conversion prints a warning for each part that could not be converted exactly.

---

## What gets converted

| Claude Code | Antigravity | How |
| :--- | :--- | :--- |
| **Plugin** (folder with `.claude-plugin/plugin.json`) | `plugins/<name>/` | Converts every component below into the plugin folder and copies every other folder and root file of the plugin (`scripts/`, `server/`, `bin/`, `node_modules/`, `LICENSE`, ...). The generated `plugin.json` keeps only `name` and `description`, the fields Antigravity's schema allows. Components declared in the Claude Code `plugin.json` (`commands`, `skills`, `agents`, `hooks`, `mcpServers`) are honored. |
| **Commands** (`commands/*.md`, `.claude/commands/*.md`, `prompts/*.md`) | `skills/<name>/SKILL.md` | The skill name comes from the file path, as in Claude Code: `commands/git/commit.md` (`/git:commit`) becomes `git-commit`. `description`, `when_to_use` and `argument-hint` go into the skill description. Argument placeholders follow Claude Code: `$ARGUMENTS`, `$ARGUMENTS[N]`, `$N` (zero-based: `$0` is the first argument) and named arguments from `arguments`; `\$1`, code blocks and amounts such as `$50` are left alone. |
| **Skills** (`skills/<name>/SKILL.md`) | `skills/<name>/SKILL.md` | Copies the whole skill folder (`references/`, `scripts/`, ...) and aligns `name:` with the folder name. Argument placeholders in `SKILL.md` follow the same rules as commands (a skill without placeholders is left as is); `${CLAUDE_SKILL_DIR}` becomes the absolute path of the converted skill and `${CLAUDE_PROJECT_DIR}` becomes `.`; `${CLAUDE_SESSION_ID}` and `${CLAUDE_EFFORT}` have no equivalent and are reported. |
| **Subagents** (`agents/*.md`, `.claude/agents/*.md`) | `agents/<name>.md` | Maps tool names (`Read` to `view_file`, `Bash` to `run_command`, `Edit` to `replace_file_content` and `multi_replace_file_content`, ...) and removes tools Antigravity lacks, with a warning. `haiku` becomes `flash`; `sonnet`, `opus` and `fable` become `pro` (an assumed correspondence, not documented). |
| **Rules** (`CLAUDE.md`) | `AGENTS.md` (`rules/AGENTS.md` with `--install`) | Removes YAML frontmatter, adds a provenance comment and warns when the file exceeds Antigravity's 24 KB per-file limit ([Rules](https://antigravity.google/docs/rules)). In a plugin, `CLAUDE.md` is not converted, because Claude Code does not load it there; the one at the plugin root is copied as it is. |
| **MCP servers** (`.mcp.json`, `mcp.json`, `.claude.json`) | `mcp_config.json` | Writes the `mcpServers` root; remote servers get `serverUrl` and keep their `headers`. Warns about plaintext credentials and about `headersHelper` and `oauth`, which are not converted. |
| **Hooks** (`hooks/hooks.json`, `.claude/settings.json`, `.claude/settings.local.json`) | `hooks.json` | See [Hooks](#hooks). |
| **Plugin variables** | resolved values | `${CLAUDE_PLUGIN_ROOT}` becomes the absolute path of the converted plugin; `${CLAUDE_PLUGIN_DATA}` becomes its `cc2agy_data/` folder; `${user_config.KEY}` takes the value from `--user-config` or the declared `default`. |

Components with no Antigravity equivalent (output styles, LSP servers, workflows, themes, monitors, plugin `settings.json`, `channels`, `dependencies`, `.mcpb` and `.dxt` bundles) are reported, not converted. `bin/` is copied, but Antigravity does not put it on the `PATH`.

### Hooks

Antigravity's hook events, input and output differ from Claude Code's. cc2agy writes a small runner, `cc2agy_hooks/hook_runner.py`, next to `hooks.json`, and every converted Claude Code hook runs through it.

| Claude Code event | Antigravity event | Behavior |
| :--- | :--- | :--- |
| `SessionStart` | `PreInvocation` | Runs once per conversation; its output becomes context. Only the `startup` source exists in Antigravity. |
| `UserPromptSubmit` | `PreInvocation` | Runs before every model call, not once per message; its output becomes context. |
| `PreToolUse` | `PreToolUse` | Exit code 2, `permissionDecision` (`allow`, `deny`, `ask`) and the older `decision` field become Antigravity's `decision`. `updatedInput` becomes `ask`, since Antigravity cannot change the tool input. |
| `PostToolUse` | `PostToolUse` | Runs for its side effects; what it asks for (blocking, extra context) has no equivalent and is reported on stderr. |
| `Stop` | `Stop` | A request to keep working (exit code 2 or `decision: "block"`) becomes `decision: "continue"`; `stop_hook_active` is emulated. |

The runner also gives hooks what Claude Code gives them:
- Claude Code input fields (`session_id`, `cwd`, `hook_event_name`, `tool_name`, `tool_input`, ...). Tool names and arguments are translated for `Read`, `Write`, `Edit`, `Bash`, `WebFetch` and `WebSearch`; other tools keep their Antigravity names.
- The project folder as working directory.
- The environment variables `CLAUDE_PROJECT_DIR`, `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA` and `CLAUDE_PLUGIN_OPTION_<KEY>`.
- UTF-8 input and output on any system code page.

`SessionStart` and `Stop` hooks are skipped inside subagents, as in Claude Code. Matchers are translated (`Bash` to `run_command`, `Read` to `view_file`, ...).

Project hooks from `.claude/settings.json` and `.claude/settings.local.json` are added up as Claude Code does: a hook defined in both files runs once, and `disableAllHooks` follows settings precedence (the local file wins). Other settings keys (`permissions`, `env`, ...) are not converted. Hook types other than `command` (`http`, `prompt`, `agent`, `mcp_tool`) are reported and skipped.

---

## Quick start

Run straight from a clone (no installation):

```bash
git clone https://github.com/azsak00/cc2agy.git
cd cc2agy
python cc2agy.py inspect path/to/claude-plugin
python cc2agy.py convert path/to/claude-plugin --install project
```

Or install the `cc2agy` command:

```bash
pip install -e .
cc2agy convert path/to/claude-plugin --install project
```

`--install project` writes into `.agents/` of the **current folder**, so run it from the Antigravity workspace that should use the converted files.

---

## CLI reference

### `inspect`

Lists the Claude Code components found in a folder or file, without changing anything. Exits with code 1 when nothing is found.

```bash
python cc2agy.py inspect <path>
```

### `convert`

```bash
python cc2agy.py convert <path> [options]
```

| Option | Default | Description |
| :--- | :--- | :--- |
| `--dest`, `-d` | `./output` | Destination folder. A plugin goes to `<dest>/plugins/<name>/`. |
| `--install project\|user` | | Convert straight into the folders Antigravity reads: `.agents/` in the current folder (`project`) or `~/.gemini/config/` (`user`). An existing `mcp_config.json` or `hooks.json` there is merged, not replaced: servers and hook groups already present are kept, and the previous file is saved as `<file>.cc2agy.bak`. Cannot be combined with `--dest`. |
| `--overwrite` | off | Replace files, skills, MCP servers and hook groups that already exist in the destination. |
| `--plugin` | off | Package the target as a plugin even without `.claude-plugin/plugin.json`. |
| `--user-config KEY=VALUE` | | Value for a `userConfig` key of the plugin (repeatable). Antigravity cannot prompt for these values, so they are written into the converted plugin. |
| `--skills-only` | off | Convert only commands and skills. |
| `--rules-only` | off | Convert only `CLAUDE.md`. |
| `--mcp-only` | off | Convert only MCP servers. |
| `--hooks-only` | off | Convert only hooks. |
| `--version`, `-v` | | Show the version. |

Subagents are converted only when no `--*-only` filter is used. A folder with `.claude-plugin/plugin.json` is converted as a plugin unless a filter is used.

---

## Examples

The outputs below come from real runs of the current version, with paths shortened and some lines left out.

### 1. An official plugin into the current workspace

```bash
python cc2agy.py convert path/to/commit-commands --install project
```

```text
  [+] Full Plugin packaged: commit-commands -> <workspace>\.agents\plugins\commit-commands
      - Skills/Commands: 3
      [!] Warning: Command '...\commands\commit.md': fields with no Antigravity skill equivalent were dropped: allowed-tools.
```

The three commands become `skills/clean-gone`, `skills/commit` and `skills/commit-push-pr` inside the plugin; `LICENSE` and `README.md` are copied.

### 2. A project folder

A project with two commands (`review.md` and `git/commit.md`), a subagent, a hook in `.claude/settings.json`, `CLAUDE.md` and `.mcp.json`, converted from inside the project:

```bash
cd my-app
python path/to/cc2agy.py convert . --install project
```

```text
  [+] Skill generated: git-commit -> <my-app>\.agents\skills\git-commit\SKILL.md
  [+] Skill generated: review -> <my-app>\.agents\skills\review\SKILL.md
  [+] Rules generated: AGENTS.md -> <my-app>\.agents\rules\AGENTS.md
  [+] MCP config generated: mcp_config.json -> <my-app>\.agents\mcp_config.json
  [+] Hooks generated: hooks.json -> <my-app>\.agents\hooks.json
      [!] Warning: settings.json: only hooks are converted; not converted: permissions.
  [+] Subagent generated: checker -> <my-app>\.agents\agents\checker.md
      [!] Warning: Agent 'checker': tools without an Antigravity equivalent were removed: TodoWrite.
```

The subagent's `tools: Read, Grep, Glob, TodoWrite` and `model: haiku` became `view_file`, `grep_search`, `find_by_name`, `list_dir` and `model: flash`.

### 3. A plugin with `userConfig`

The plugin declares `notes_dir` (no default) and `max_results` (default `10`), and its MCP server uses `${CLAUDE_PLUGIN_ROOT}` and both values:

```bash
python cc2agy.py convert notes-plugin --dest out --user-config notes_dir=D:/Notes
```

The generated `out/plugins/notes/mcp_config.json`:

```json
"search": {
  "command": "node",
  "args": ["<cwd>/out/plugins/notes/server/index.js", "--dir", "D:/Notes", "--max", "10"],
  "env": {
    "CLAUDE_PLUGIN_ROOT": "<cwd>/out/plugins/notes",
    "CLAUDE_PLUGIN_DATA": "<cwd>/out/plugins/notes/cc2agy_data"
  }
}
```

Without `--user-config notes_dir=...`, the placeholder stays as is and the conversion says which option to pass.

---

## Where Antigravity reads converted files

| Resource | Workspace | All workspaces |
| :--- | :--- | :--- |
| Plugins | `.agents/plugins/<name>/` | `~/.gemini/config/plugins/<name>/` (CLI: `~/.gemini/antigravity-cli/plugins/<name>/`) |
| Skills | `.agents/skills/<name>/SKILL.md` | `~/.gemini/config/skills/<name>/SKILL.md` |
| Subagents | `.agents/agents/<name>.md` | `~/.gemini/config/agents/<name>.md` |
| Rules | `AGENTS.md`, `GEMINI.md` or `.agents/rules/*.md` | `~/.gemini/AGENTS.md`, `~/.gemini/GEMINI.md` or `~/.gemini/config/rules/*.md` |
| MCP servers | `.agents/mcp_config.json` | `~/.gemini/config/mcp_config.json` |
| Hooks | `.agents/hooks.json` | `~/.gemini/config/hooks.json` |

Sources: Antigravity documentation on [plugins](https://antigravity.google/docs/plugins), [skills](https://antigravity.google/docs/skills), [subagents](https://antigravity.google/docs/subagents), [rules](https://antigravity.google/docs/rules), [MCP](https://antigravity.google/docs/mcp) and [hooks](https://antigravity.google/docs/hooks). On Windows, `~` is `C:\Users\<user>`.

---

## Upgrading from earlier versions

Converting again with a newer cc2agy can change results. Skills, subagents and files from the previous conversion stay in the destination until you delete them.

- Commands in subfolders are named after the folder: `commands/git/commit.md` became `git-commit` (it was `commit`).
- The `name:` field of a command is ignored, as in Claude Code; the name comes from the file path.
- Argument numbers start at zero, as in Claude Code: `$1` is now the **second** argument.
- Hooks run in the project folder (they used to run in the plugin folder).
- The generated `plugin.json` keeps only `name` and `description`.
- An unreadable `plugin.json` stops the conversion with an error (it used to be ignored silently).
- Source files saved with a UTF-8 BOM (as Windows PowerShell 5.1 does) are read normally.
- Argument placeholders and `${CLAUDE_SKILL_DIR}` inside modular skills (`SKILL.md`) are converted (they used to be copied as they were).
- Plugins are searched in the same places `inspect` lists: commands in `commands/`, `.claude/commands/` and `prompts/` are all converted (only the first of the first two used to be, and `prompts/` was copied as it was), subagents in `.claude/agents/` are converted, and an MCP config in `.claude/` (`.mcp.json`, `mcp.json` or `.claude.json`) is read. A plugin with commands in more than one of these folders may produce more skills than before.
- A `CLAUDE.md` in a plugin no longer becomes `rules/AGENTS.md`, since Claude Code does not load it in a plugin; the one at the plugin root is copied as it is. The `rules/AGENTS.md` of an earlier conversion stays active in the converted plugin until you delete it.

---

## Limitations

- **Python is required for hooks.** The hook runner is called as `python` on Windows and `python3` elsewhere, found through the `PATH`.
- **Paths are absolute.** `${CLAUDE_PLUGIN_ROOT}`, `cc2agy_data/` and the runner path point to the folder chosen at conversion time; moving the converted folder breaks them. Convert straight into the final location (`--install`).
- **Subagent detection is undocumented.** Skipping `SessionStart` and `Stop` inside subagents relies on an internal Antigravity file; if a future version changes it, those hooks will also run inside subagents.
- **Values are written in plain text.** `userConfig` values are written into the converted files; `sensitive` values are kept out of skills and subagents but written into `mcp_config.json` and `hooks.json` (base64, not encryption), with a warning.
- **Not converted:** `${VAR}` expansion of arbitrary environment variables in MCP configs, `${CLAUDE_PROJECT_DIR}` in MCP configs, `SessionStart` sources other than `startup`, frontmatter fields of modular skills other than `name` (copied as they are), and the result of a tool in `PostToolUse` input (Antigravity sends only the error).
- **Tested with the Antigravity CLI** (`agy` 1.2.13 and 1.3.0, Windows), not with the IDE or `--install user`.

---

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

Run it from the repository root. The suite uses only `unittest` and runs in a few seconds.

---

## Repository structure

```text
cc2agy/
├── src/cc2agy/
│   ├── cli.py              # Command-line interface
│   ├── detector.py         # Finds Claude Code components in a folder or file
│   ├── locations.py        # Where each component is looked for (shared by detector and plugin)
│   └── converters/
│       ├── agents.py       # Subagents
│       ├── commands.py     # Commands -> Skills
│       ├── hooks.py        # Hooks and the generated hook runner
│       ├── mcp.py          # MCP servers
│       ├── plugin.py       # Whole plugins
│       ├── rules.py        # CLAUDE.md -> AGENTS.md
│       ├── skills.py       # Modular skills
│       └── variables.py    # Plugin variables and userConfig
├── tests/                  # unittest suite (one file per converter, plus install, BOM and settings hooks)
├── cc2agy.py               # Runner that works without installation
├── pyproject.toml
├── LICENSE
└── README.md
```

---

## Guia em português

O **cc2agy** converte comandos, skills, subagentes, regras (`CLAUDE.md`), servidores MCP, hooks e plugins inteiros do Claude Code para os formatos do Google Antigravity. É escrito em Python puro, sem dependências externas. Não sobrescreve nada sem `--overwrite` e avisa, a cada conversão, tudo o que não pôde ser convertido exatamente.

Os comandos viram **skills** (`SKILL.md`), e não workflows, porque a documentação do Antigravity informa que os workflows serão desativados em 1º de novembro de 2026 ([guia de migração](https://antigravity.google/docs/migration/workflows-to-skills/)).

### Como usar

1. Veja o que a pasta ou o plugin contém:

   ```bash
   python cc2agy.py inspect "caminho/para/o-plugin"
   ```

2. Abra o terminal na pasta do projeto do Antigravity e converta direto para lá:

   ```bash
   python cc2agy.py convert "caminho/para/o-plugin" --install project
   ```

   Para valer em todos os projetos, use `--install user`, que grava em `~/.gemini/config/`. Para só gerar os arquivos numa pasta, use `--dest <pasta>`.

3. Se o plugin pedir valores de configuração (`userConfig`), informe-os na conversão, porque o Antigravity não tem como pedi-los:

   ```bash
   python cc2agy.py convert "caminho/para/o-plugin" --install project --user-config pasta_notas=D:/Notas
   ```

### Opções principais

- `--dest <pasta>`: pasta de destino. Um plugin vai para `<pasta>/plugins/<nome>/`.
- `--install project|user`: converte direto para as pastas que o Antigravity lê. Um `mcp_config.json` ou `hooks.json` já existente é complementado, não substituído, e a versão anterior fica guardada em `<arquivo>.cc2agy.bak`.
- `--overwrite`: substitui o que já existe no destino.
- `--plugin`: trata a pasta como plugin mesmo sem `.claude-plugin/plugin.json`.
- `--user-config CHAVE=VALOR`: valor de configuração do plugin (pode repetir).
- `--skills-only`, `--rules-only`, `--mcp-only`, `--hooks-only`: convertem só uma parte. Os subagentes só são convertidos sem esses filtros.

### O que muda para quem já converteu antes

Ao converter de novo com a versão atual, o que veio da conversão anterior continua no destino até ser apagado à mão.

- Comandos em subpasta levam o nome da pasta: `commands/git/commit.md` virou `git-commit` (antes era `commit`).
- O campo `name:` de um comando é ignorado, como no Claude Code.
- A numeração dos argumentos começa em zero, como no Claude Code: `$1` agora é o **segundo** argumento.
- Os hooks rodam na pasta do projeto (antes rodavam na pasta do plugin).
- O `plugin.json` gerado só tem `name` e `description`.
- Um `plugin.json` ilegível interrompe a conversão com erro (antes era ignorado sem aviso).
- Arquivos gravados com BOM, como faz o PowerShell 5.1 do Windows, passaram a ser lidos normalmente.
- Nas skills modulares (`SKILL.md`), os marcadores de argumento e `${CLAUDE_SKILL_DIR}` passaram a ser convertidos (antes eram copiados como estavam).
- Nos plugins, a busca segue os mesmos lugares que o `inspect` lista: os comandos de `commands/`, `.claude/commands/` e `prompts/` são todos convertidos (antes só a primeira das duas primeiras pastas, e `prompts/` era copiada como estava), os subagentes de `.claude/agents/` são convertidos, e uma configuração MCP em `.claude/` (`.mcp.json`, `mcp.json` ou `.claude.json`) é lida. Um plugin com comandos em mais de uma dessas pastas pode gerar mais skills do que antes.
- Um `CLAUDE.md` dentro de plugin deixou de virar `rules/AGENTS.md`, porque o Claude Code não o carrega num plugin; o da raiz do plugin é copiado como está. O `rules/AGENTS.md` de uma conversão anterior continua ativo no plugin convertido até ser apagado à mão.

### Limitações

- Os hooks exigem Python no `PATH` (`python` no Windows, `python3` nos demais sistemas).
- Os caminhos gerados são absolutos: se a pasta convertida for movida, é preciso converter de novo. Converta direto no destino final, com `--install`.
- Valores de `userConfig` ficam gravados nos arquivos convertidos; os marcados como `sensitive` ficam fora de skills e subagentes, mas entram no `mcp_config.json` e no `hooks.json`, com aviso.
- O teste real foi feito na CLI do Antigravity (`agy` 1.2.13 e 1.3.0, no Windows), não na IDE nem com `--install user`.
- A lista completa está na seção [Limitations](#limitations).

---

## License

[MIT](LICENSE). Copyright (c) 2026 cc2agy Contributors.
