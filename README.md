# shesh-acp

**Agent Client Protocol (ACP) server** — Shesh runs inside Zed/JetBrains with streaming + permissions.

- Layer: Soma (Soma)
- License: MIT
- Part of: [Shesh ecosystem](https://github.com/gaganjainse/shesh-ecosystem)

---
**Agent Client Protocol (ACP) server for Shesh.** Lets the agent run inside Zed, JetBrains,
Neovim, and other ACP editors — streaming token updates, permission requests, and scoped
file/terminal access — while the Brain's policy still governs every action.

- License: GPL-3.0
- Spans: Soma (editor surface) + Mind (drives the coder agent)
- Part of: [Shesh ecosystem](https://github.com/gaganjainse/shesh-ecosystem)

## Scope

Implements a minimal, tested subset of ACP (JSON-RPC 2.0 over stdio):

- `initialize` capability negotiation
- `session/new`
- `fs/read_text_file`, `fs/write_text_file`, `fs/list` (path-traversal safe, policy-gated)
- `session/prompt` with streaming `session/update` notifications

MCP is the inner layer (agent→tools); ACP is the outer layer (editor→agent). The ACP server
spawns `shesh-orchestrator` (P1) and hands it the MCP endpoints. For now it ships with a stub
agent so the protocol and policy are testable end-to-end.

## Develop

```bash
uv sync --extra dev
uv run pytest -q          # offline, no stdio/LLM needed
uv run ruff check .
uv run shesh-acp          # runs the stdio server
```

## Roadmap

- terminal create/exec with permission prompts
- real `shesh-orchestrator` integration (coder role, MCP endpoints)
- diff/update messages for editor review
- session persistence and A2A subagent messaging