<!-- AGENTS.md — Diretrizes de Engenharia e Governança do Projeto cc2agy -->

# Governança do Repositório: cc2agy

Este repositório destina-se a fornecer uma ferramenta CLI e biblioteca moderna, em Python puro e de alta confiabilidade, para converter plugins, comandos, regras e configurações MCP do ecossistema Claude Code para os padrões canônicos do Google Antigravity.

---

## 1. Princípios Arquiteturais Mandatórios

1. **Python Puro (Zero Dependências Externas em Runtime):**
   - O núcleo do `cc2agy` deve utilizar exclusivamente a biblioteca padrão do Python (`argparse`, `pathlib`, `json`, `re`, `shutil`, `unittest`).
   - Qualquer usuário em Windows, macOS ou Linux deve conseguir executar a ferramenta imediatamente sem necessidade de compilação ou instalação pesada de dependências de terceiros.
2. **Fidelidade aos Padrões Canônicos do Antigravity:**
   - **Comandos do Claude (`commands/*.md`)**: Devem ser convertidos em **Skills** nativas (`skills/<nome>/SKILL.md`) com frontmatter YAML (`name`, `description`) e suporte nativo a comandos com barra `/<nome>`. Não gerar *workflows* legados (`.md` em `workflows/`).
   - **Regras do Claude (`CLAUDE.md`)**: Devem ser convertidas para regras de governança (`AGENTS.md`), removendo qualquer frontmatter YAML (não suportado em `AGENTS.md`).
   - **Configuração MCP (`.mcp.json`)**: Deve ser convertida em `mcp_config.json` com nó raiz `"mcpServers"` e validação estrita de campos (`command`, `args`, `env`).
3. **Não-Destrutividade e Segurança:**
   - Nenhuma conversão deve sobrescrever arquivos silenciosamente. Sempre fornecer feedback explícito das operações de escrita e preservar arquivos originais.
4. **Testes Automatizados:**
   - Todo conversor deve possuir cobertura com a suíte nativa `unittest` em `tests/`.
