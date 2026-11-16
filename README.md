# Skill improvement cycle

A staged demo: start with a procedure in Markdown, generate code to execute it, then reuse a validated script inside the skill.

## Phase 1 — Shared foundation

This checkout contains the orders simulator and native MCP connections. Agent behavior is introduced in the next phases.

| Component | Purpose |
| --- | --- |
| Orders app | Generate synthetic orders, controlled failures and recovery |
| MongoDB | Persist customers, orders and synchronization attempts with native ObjectIds |
| Logfire | Receive simulator traces and expose evidence through MCP |
| Gmail through Composio | Provide the incident email |
| Notion through Composio | Store the investigation result |

The simulator uses PyMongo and Logfire directly. Agent integrations expose the full native MCP toolsets through capabilities with deferred loading. Application procedures will live in the skill, not in integration wrappers.

## Setup

Install Docker with Compose, uv, Python 3.13, Node 22.12+ and npm. Docker must be running for local data checks.

```sh
make setup
```

Setup installs locked Python and Node dependencies and creates private `.env` files from the committed examples only when missing. It does not start services or call external APIs. Set `CUSTOMER_EMAIL` in `orders-app/.env` to the sender address you will use before seeding.

Mongo runs on `127.0.0.1:27029`, in this repository's Compose project and volume, separate from the earlier demo. The default application database is `skill_orders_demo`.

## Test the orders application

First set `LOGFIRE_TOKEN` in `orders-app/.env` to a project write token. Both seed and recovery always send traces to Logfire and stop before changing orders if the token is missing. Mongo remains local.

```sh
make seed SCENARIO=demo
make check-mcp SERVICE=mongo
make test
make recover SCENARIO=demo
make status
make down
```

The seed produces two customers, six orders and six attempts: three orders fail for Aster Labs because credential renewal is rejected; the control customer's three orders synchronize. Recovery retries the three failed orders, preserving their prior attempts. Both commands send telemetry to Logfire and also display it in the console.

Seeding is idempotent: rerunning a scenario does not reset recovered orders or change an existing customer's email. Use a new `SCENARIO` to create a fresh incident or after changing `CUSTOMER_EMAIL`. `down` preserves the data volume. Simulator tests use temporary databases and delete only those databases; they do not alter the demo scenario or send telemetry externally. Connection tests use an in-memory HTTP transport to verify Composio account selection and session requests without external access.

## Start the orders scenario again

```sh
make reset-orders
make seed
```

`reset-orders` clears the `orders` and `sync_attempts` collections across all scenarios in the configured application database. It preserves customers, their ObjectIds, names and emails, all indexes and other collections. It resets only the demo customers' connection fields: Aster returns to rejected credential renewal and Cedar remains healthy. This restores the failure scenario even after recovery. The command starts Mongo if needed, does not reseed automatically and needs no Logfire token. The following `seed` reuses customers in the same scenario and creates fresh orders and attempts. It creates customers only when the selected scenario does not already contain them; changing `SCENARIO` intentionally creates a separate pair.

Other Mongo databases, Gmail messages, Notion incidents and historical Logfire traces remain unchanged. This phase has no Temporal schedules or worker to stop. Do not run seed, recovery or another database operation concurrently with reset.

## Connect the external sources

1. In `orders-app/.env`, set `LOGFIRE_TOKEN` to a project write token. To generate real evidence, run `make seed SCENARIO=live-demo`. Use `make recover SCENARIO=live-demo` later to trace recovery.
2. In `investigation-agent/.env`, set a Logfire API key with `project:read` access. Set `LOGFIRE_MCP_URL` to your region's endpoint (the example uses EU). Set `LOGFIRE_PROJECT` to the project containing the simulator traces. This will guide the agent queries in phase 2; the phase-1 connectivity check only lists tools. Trace ingestion selects its destination through the simulator write token, not this variable. The agent environment also includes `LOGFIRE_TOKEN` for its own execution traces in phase 2. Use a write token from the same project; the agent will use a separate service name from the orders simulator. Phase 1 connection checks do not emit agent traces.
3. In Composio, connect the Gmail inbox and Notion workspace. Put the Composio API key and both connected-account IDs in `investigation-agent/.env`. The key must allow reading connected accounts and creating tool-router sessions; executing tools in later phases also needs execution permission.
4. Give the Notion connection access to an `Incidents` database with the properties below.

| Property | Notion type |
| --- | --- |
| Incident | Title |
| Status | Select: Open, Investigating, Awaiting intervention, Resolved |
| Customer | Text |
| Email | Email |
| Gmail Message ID | Text |
| Created | Created time |

```sh
make check-mcp
# Or check just one service:
make check-mcp SERVICE=gmail
```

`make check-mcp` checks Logfire, Gmail, Notion and Mongo by default, reporting each result even if another connection fails. It exits unsuccessfully if any check fails. Use `SERVICE=logfire|gmail|notion|mongo` to select one service. These checks initialize MCP and list its tools. Composio checks create an application-scoped session. They do not read email messages, execute application tools or write Notion pages. Successful tool listing proves connectivity, not that the future investigation workflow works.

Private credentials are ignored by Git. No credentials, connected-account IDs or private data are bundled in this repository. No model key is needed in phase 1.

## Repository layout

```text
orders-app/                    Simulator, integration tests and Python lockfile
investigation-agent/
  src/investigation_agent/
    capabilities/              Native MCP toolset composition
    integrations/composio.py   Composio session connection
    connections.py            Explicit MCP connectivity check
  mcp/mongodb/                 Official Node MCP server and npm lockfile
compose.yaml                   Local MongoDB
Makefile                       Setup, simulator and connection commands
```

## Planned checkpoints

1. Shared foundation (this phase).
2. Markdown skill with direct MCP tool calls.
3. The same procedure with model-generated Code Mode programs.
4. A validated parameterized script bundled with the skill.

Each phase will be reviewed before its commit. Tags for the three agent stages will be created when those stages are validated. Temporal and automated follow-up are outside the initial talk's three-stage comparison.

## Dependency review note

The pinned official MongoDB MCP server is version 3.3.0. At preparation time, `npm audit` reported advisories in its transitive `basic-ftp` dependency, propagated through proxy-support packages. The demo connects Mongo locally through stdio; this does not establish that the dependency is safe in every deployment. No forced downgrade or incompatible override has been applied. Review upstream fixes before broader distribution; inspect the current report with `npm audit --prefix investigation-agent/mcp/mongodb`.
