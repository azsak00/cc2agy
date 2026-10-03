# cc2agy 🚀

> **Bridge and migration tool from Claude Code to Google Antigravity.**  
> *Seamlessly convert Claude Code commands, plugins, rules, and MCP configurations into native Google Antigravity Skills and configurations in seconds.*

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)]()
[![Platform: Win | Mac | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

---

## ⚡ What is cc2agy?

Anthropic's **Claude Code** has a vibrant ecosystem of custom slash commands, plugins, project instructions, and Model Context Protocol (MCP) servers.

**cc2agy** is an open-source, zero-dependency bridge tool written in pure Python that translates your Claude Code workflows and plugins into modern, fully compatible **Google Antigravity** resources:

- 🪄 **Commands to Skills:** Translates Claude Code commands (`commands/*.md`) directly into canonical Antigravity **Skills** (`SKILL.md`), enabling native slash-command invocation (`/<command>`) and progressive disclosure.
- 📋 **Instructions to Governance:** Converts `CLAUDE.md` project rules into clean Antigravity `AGENTS.md` governance files.
- 🔌 **MCP Tool Integration:** Automatically converts `.mcp.json` into canonical `mcp_config.json` definitions.
- 🛡️ **Zero Dependencies:** Pure Python standard library. No `pip install` headaches, no compilation, runs instantly anywhere.

---

## 🗺️ Architectural Mapping

| Claude Code Resource | Source Format | Canonical Antigravity Target | Conversion Behavior |
| :--- | :--- | :--- | :--- |
| **Commands** | `commands/<name>.md` | `skills/<name>/SKILL.md` | Generates modern Antigravity Skills with YAML frontmatter (`name`, `description`) enabling slash-command trigger. |
| **Modular Skills** | `skills/<name>/SKILL.md` | `skills/<name>/SKILL.md` | Preserves folder structure, scripts, and progressive disclosure references. |
| **Project Rules** | `CLAUDE.md` | `AGENTS.md` | Strips unsupported YAML frontmatter, formats as imperative governance rules. |
| **MCP Config** | `.mcp.json` | `mcp_config.json` | Maps server definitions into the standard `"mcpServers"` JSON structure. |

---

## 🚀 Quick Start (1 Minute)

### 1. Direct Execution (No Installation Required)

Clone the repository and run directly with Python:

```bash
python -m src.cc2agy convert path/to/claude-plugin --dest ~/.gemini/config/skills/
```

### 2. Standard CLI Usage

```bash
# Convert a single command or an entire Claude Code plugin/workspace
python -m cc2agy convert ./my-claude-project --dest ./output

# Inspect and preview what will be converted without modifying files
python -m cc2agy inspect ./my-claude-project
```

---

## 📁 Repository Structure

```text
cc2agy/
├── src/
│   └── cc2agy/
│       ├── __init__.py           # Package exports & version
│       ├── cli.py                # Command-line interface
│       ├── detector.py           # Auto-detection of Claude Code assets
│       ├── core.py               # Conversion orchestrator
│       └── converters/
│           ├── __init__.py
│           ├── commands.py       # Commands -> Skills converter
│           ├── rules.py          # CLAUDE.md -> AGENTS.md converter
│           └── mcp.py            # .mcp.json -> mcp_config.json converter
├── tests/                        # Automated unit tests (built-in unittest)
├── pyproject.toml                # Standard PEP 621 packaging
├── LICENSE                       # MIT License
└── README.md                     # Documentation
```

---

## 🇧🇷 Resumo em Português

O **cc2agy** é uma ferramenta de ponte em Python puro (sem dependências externas) projetada para converter comandos, habilidades, regras (`CLAUDE.md`) e servidores MCP do Claude Code para o padrão moderno do Google Antigravity. 

Ele converte comandos do Claude diretamente para **Skills nativas** com suporte a comandos de barra (`/<comando>`), eliminando formatos obsoletos e garantindo funcionamento imediato no Antigravity no Windows, macOS e Linux.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
