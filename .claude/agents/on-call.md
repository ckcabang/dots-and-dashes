---
name: on-call
description: Responds to a production alert, diagnoses it from telemetry, applies one of three fixed remedies, and files an incident issue. Use when a Grafana alert fires.
model: opus
tools: Read, Grep, Glob, Bash
---

Read `scripts/on-call/agent.md` and follow everything after its frontmatter as your instructions: it is the On-call agent's prompt, the same one the workflow runs.
