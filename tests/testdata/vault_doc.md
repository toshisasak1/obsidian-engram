---
tags:
  - project
  - architecture
created: 2026-03-15
---

# Architecture Decision Record

## Context

We need to choose a database for the new service.

## Decision

We chose PostgreSQL for its JSONB support and strong consistency guarantees.

## Consequences

- Need to manage connection pooling
- Schema migrations become critical
- Good ecosystem of tools and ORMs
