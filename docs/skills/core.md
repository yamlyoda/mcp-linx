# Core — идеология Skills (Harness)

Часть Skills (см. `docs/SKILLS.md`). Читать, только если пишете свой плагин или ревьюите архитектуру — для диагностики не нужно.

## Overview

Skills in MCP-Linx follow the **Harness ideology**: skills are plugins that can be loaded, combined, and swapped via configuration.

## What is a Skill?

A **skill** is a reusable capability combining:
- **Tools** — MCP tools for specific operations
- **Knowledge** — domain-specific information
- **Workflows** — common operation patterns

## Best Practices

1. **Single Responsibility** — Each tool does one thing
2. **Idempotent** — Same input, same output
3. **Safe** — Read-only by default
4. **Fast** — Return quickly
5. **Structured Output** — Use dicts, not strings
