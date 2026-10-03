# cc2agy 🚀

> **Bridge and migration tool from Anthropic Claude Code to Google Antigravity.**  
> *Seamlessly convert Claude Code commands, plugins, rules, and MCP configurations into native Google Antigravity Skills and configurations in seconds.*

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)]()
[![Platform: Win | Mac | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()
[![Tests: 29 Passing](https://img.shields.io/badge/tests-29%20passed-brightgreen.svg)]()
[![Antigravity 2.0 Ready](https://img.shields.io/badge/Antigravity-2.0%20Ready-blueviolet.svg)](https://antigravity.google)

---

## 🌐 Language / Idioma
- [English Documentation](#-what-is-cc2agy)
- [Guia Operacional em Português](#-guia-operacional-em-português)

---

## ⚡ What is cc2agy?

Anthropic's **Claude Code** has built a vibrant ecosystem of custom slash commands, plugins, project instructions, and Model Context Protocol (MCP) servers. However, developers and legal/knowledge professionals adopting **Google Antigravity** face a challenge: how to reuse existing tools and workflows without re-engineering everything from scratch.

Legacy bridges attempted to convert commands into Antigravity *workflows* (`.md` files in `workflows/`), a format that Google has formally deprecated in favor of native **Skills** (`SKILL.md`).

**cc2agy** is a modern, open-source bridge tool written in **pure Python** (standard library only, zero external runtime dependencies) that translates Claude Code workflows and plugins directly into canonical Antigravity resources:

- 🪄 **Commands to Native Skills:** Converts Claude Code commands (`commands/*.md`) into full Antigravity **Skills** (`skills/<name>/SKILL.md`) with valid YAML frontmatter (`name`, `description`), preserving prompt parameters (`$1, $2, ...` and `$*`) while shielding currency signs (`$50`) and shell scripts (`awk`).
- 📋 **Rules to Workspace Governance:** Converts `CLAUDE.md` files into clean, YAML-free `AGENTS.md` governance files, monitoring context budget limits (< 24 KB) and adding non-intrusive provenance comments.
- 🔌 **MCP Server Normalization:** Translates `.mcp.json` and `.claude.json` into canonical `mcp_config.json` configurations with the required `"mcpServers"` root key, mapping remote SSE endpoints to `serverUrl` and detecting unescaped plaintext tokens.
- 🛡️ **Zero Dependencies & Safe:** Operates strictly on Python 3.10+ standard libraries. Includes strict overwrite protection (`--overwrite`), ASCII-safe Unicode transliteration (`validação` ➔ `validacao`), and cross-platform path handling for Windows, macOS, and Linux.

---

## 🗺️ Architectural Mapping Matrix

| Claude Code Resource | Source Format | Canonical Antigravity Target | Conversion Behavior |
| :--- | :--- | :--- | :--- |
| **User Slash Commands** | `commands/<name>.md` | `skills/<name>/SKILL.md` | Generates modern Antigravity Skills with YAML frontmatter (`name`, `description`), enabling native slash-command invocation (`/<command>`). |
| **Modular Skills** | `skills/<name>/SKILL.md` | `skills/<name>/SKILL.md` | Preserves folder structure, auxiliary scripts (`scripts/`), and progressive disclosure references (`references/`). |
| **Project Rules** | `CLAUDE.md` | `AGENTS.md` | Strips unsupported YAML frontmatter, formats as imperative governance rules, and warns if context budget exceeds 24 KB. |
| **MCP Server Config** | `.mcp.json` / `.claude.json` | `mcp_config.json` | Normalizes server definitions into standard root `{"mcpServers": ...}`, maps SSE `url`/`endpoint` to `serverUrl`, and alerts on plaintext credentials. |

---

## 🚀 Quick Start (1 Minute)

### 1. Direct Execution (Zero-Config, No Installation Required)

Clone the repository and run directly with Python:

```bash
# Clone the repository
git clone https://github.com/azsak00/cc2agy.git
cd cc2agy

# Inspect discovered Claude Code resources in a plugin or folder
python cc2agy.py inspect path/to/claude-plugin

# Convert all discovered resources into Antigravity assets
python cc2agy.py convert path/to/claude-plugin --dest path/to/destination/
```

### 2. Global / Virtualenv Installation (Editable Mode)

Install as a command-line executable via pip:

```bash
pip install -e .
cc2agy inspect path/to/claude-plugin
cc2agy convert path/to/claude-plugin --dest path/to/destination/
```

---

## 🛠️ CLI Command Reference

### `inspect` — Discover & Analyze
Scans a target directory or file, reporting all detected commands, rules, and MCP configurations without making any changes.

```bash
python cc2agy.py inspect <path-to-file-or-dir>
```

**Example Output:**
```text
Analysis of: ~/.claude/plugins/marketplaces/claude-plugins-official/plugins/commit-commands
  [+] Claude Code components found:
    - Commands (3 files in [commands]):
        /clean_gone
        /commit-push-pr
        /commit
```

### `convert` — Migrate to Antigravity
Converts discovered Claude Code assets into canonical Antigravity files.

```bash
python cc2agy.py convert <target> [OPTIONS]
```

#### Available Options:
| Flag | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--dest` | `-d` | `./output` | Destination directory where converted Antigravity assets will be saved. |
| `--overwrite` | | `False` | Overwrite existing files in destination directory without error. |
| `--skills-only` | | `False` | Convert only commands into Antigravity Skills. |
| `--rules-only` | | `False` | Convert only `CLAUDE.md` into `AGENTS.md` governance rules. |
| `--mcp-only` | | `False` | Convert only MCP configuration into `mcp_config.json`. |
| `--version` | `-v` | | Show current cc2agy version. |

---

## 💡 Real-World Conversion Examples

### Example 1: Converting an Official Slash Command Plugin
Migrate Anthropic's official `commit-commands` plugin into your local project's skills:

```bash
python cc2agy.py convert path/to/commit-commands --dest .agents/skills/ --overwrite
```
**Result:**
- Generates `.agents/skills/clean-gone/SKILL.md`
- Generates `.agents/skills/commit-push-pr/SKILL.md`
- Generates `.agents/skills/commit/SKILL.md`
- Immediately available in Antigravity via `/clean-gone`, `/commit-push-pr`, and `/commit`.

### Example 2: Converting an MCP Tool Plugin
Migrate Microsoft's `playwright` MCP plugin configuration:

```bash
python cc2agy.py convert path/to/playwright --dest .agents/ --mcp-only
```
**Result:**
- Generates `.agents/mcp_config.json` with normalized `playwright` stdio server entry.

### Example 3: Converting Project Rules (`CLAUDE.md` ➔ `AGENTS.md`)
Convert a repository's Claude instructions into Antigravity governance:

```bash
python cc2agy.py convert path/to/CLAUDE.md --dest ./ --rules-only
```
**Result:**
- Generates `AGENTS.md` with clean Markdown rules, stripped YAML frontmatter, and context tracking.

---

## 📂 Antigravity Destination Guide

Where should you place converted assets in Google Antigravity?

| Scope | Resource Type | Target Path in Antigravity | Description |
| :--- | :--- | :--- | :--- |
| **Workspace Scope**<br>*(Active Project Only)* | **Skills** | `<workspace>/.agents/skills/<name>/SKILL.md` | Available only in the current workspace. |
| | **Rules** | `<workspace>/AGENTS.md` | Active governance for the current workspace. |
| | **MCP** | `<workspace>/.agents/mcp_config.json` | Project-specific MCP servers. |
| **Global Scope**<br>*(All Workspaces)* | **Skills** | `~/.gemini/config/skills/<name>/SKILL.md` | Available across all workspaces and conversations. |
| | **MCP** | `~/.gemini/config/mcp_config.json` | Global MCP servers active everywhere. |

> **Note on Windows:** `~` resolves to `C:\Users\<username>`.

---

## 🧪 Automated Test Suite

`cc2agy` includes 29 automated unit tests covering command parsing, YAML multiline scalar handling, Unicode sanitization, currency symbol shielding, rule cleaning, MCP schema normalization, and CLI workflows.

Run the test suite using Python's native `unittest` runner:

```bash
python -m unittest discover tests -v
```

All 29 tests run in under 0.15 seconds with zero external test runners required.

---

## 📁 Repository Structure

```text
cc2agy/
├── src/
│   └── cc2agy/
│       ├── __init__.py           # Package version (0.1.0)
│       ├── __main__.py           # Module execution entrypoint
│       ├── cli.py                # Command-line interface & argument parsing
│       ├── detector.py           # Auto-detection of Claude Code assets
│       └── converters/
│           ├── __init__.py       # Package exports
│           ├── commands.py       # Commands -> Skills converter
│           ├── rules.py          # CLAUDE.md -> AGENTS.md converter
│           └── mcp.py            # .mcp.json -> mcp_config.json converter
├── tests/
│   ├── __init__.py               # Test path initialization
│   ├── test_commands.py          # Command converter & detector tests
│   └── test_rules_mcp.py         # Rules, MCP & CLI integration tests
├── .agents/
│   └── rules/
│       └── AGENTS.md             # Canonical workspace governance rules
├── cc2agy.py                     # Standalone CLI runner (zero-config)
├── pyproject.toml                # Standard PEP 621 packaging metadata
├── LICENSE                       # MIT License
└── README.md                     # Documentation (EN & PT-BR)
```

---

## 🇧🇷 Guia Operacional em Português

O **cc2agy** é uma ferramenta de ponte e migração em **Python puro** projetada para permitir que usuários do **Google Antigravity** aproveitem plugins, comandos de barra (`/comando`), regras de contexto e ferramentas MCP do ecossistema Claude Code sem atrito.

### Por que o cc2agy foi criado?
Muitos profissionais (incluindo advogados e usuários não técnicos) utilizam rotinas avançadas no Claude Code e desejam migrar para o Google Antigravity. As soluções antigas tentavam converter comandos para "workflows", um formato que o Antigravity descontinuou. O **cc2agy** converte comandos diretamente para **Skills Nativas** (`SKILL.md`), garantindo acionamento instantâneo via barra (`/`) e conformidade total com as diretrizes oficiais da Google.

### Como Usar em 3 Passos Simples

#### Passo 1: Inspecionar o plugin ou pasta
Verifique o que o plugin contém antes de converter:
```bash
python cc2agy.py inspect "caminho/para/pasta-do-plugin"
```

#### Passo 2: Converter para seu projeto atual (Escopo do Workspace)
Gere as Skills e regras diretamente na pasta `.agents` do seu projeto:
```bash
python cc2agy.py convert "caminho/para/pasta-do-plugin" --dest .agents/skills/ --overwrite
```

#### Passo 3: Ou converter para uso global em todos os seus projetos
Se quiser que o comando funcione em qualquer conversa do Antigravity na sua máquina:
```bash
python cc2agy.py convert "caminho/para/pasta-do-plugin" --dest C:/Users/seu_usuario/.gemini/config/skills/ --overwrite
```

### Principais Opções de Conversão
- `--dest <caminho>`: Define onde os arquivos convertidos serão salvos.
- `--overwrite`: Permite atualizar com segurança arquivos que já existam.
- `--skills-only`: Converte apenas os comandos/skills.
- `--rules-only`: Converte apenas o arquivo de instruções `CLAUDE.md` em `AGENTS.md`.
- `--mcp-only`: Converte apenas as configurações de servidores MCP.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
Distributed under the open-source MIT terms. Copyright (c) 2026 cc2agy Contributors.
