# TrevorAgentcoreShowcase

A showcase project built on [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/) demonstrating two Strands-based AI agents — a **SQL Assistant** and a **Schema Assistant** — deployed to AWS via CDK and GitHub Actions.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      GitHub Actions                      │
│  PR/push → test → (main) deploy dev → (tag) deploy stg  │
└──────────────────────────┬──────────────────────────────┘
                           │  agentcore deploy (CDK)
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    AWS (us-east-2)                        │
│                                                           │
│  ┌────────────────┐     ┌──────────────────────────┐    │
│  │  SqlAssistant  │     │    SchemaAssistant        │    │
│  │  CodeZip       │     │    CodeZip                │    │
│  │  Python 3.14   │     │    Python 3.14            │    │
│  │  HTTP/PUBLIC   │     │    HTTP/PUBLIC            │    │
│  └───────┬────────┘     └───────────┬──────────────┘    │
│          │                          │                     │
│          └──────────┬───────────────┘                    │
│                     │ reads                               │
│          ┌──────────▼───────────┐                        │
│          │   Secrets Manager    │                        │
│          │   TrevorShowcase/    │                        │
│          │   SqlAssistant/      │                        │
│          │   litellm            │                        │
│          └──────────┬───────────┘                        │
│                     │ LITELLM_API_KEY, LITELLM_BASE_URL  │
│          ┌──────────▼───────────┐                        │
│          │       LiteLLM        │                        │
│          │  (VTS model proxy)   │                        │
│          └──────────────────────┘                        │
└─────────────────────────────────────────────────────────┘
```

### Agents

Both agents are [Strands](https://strandsagents.com) agents deployed as `CodeZip` runtimes under the `TrevorShowcase` project:

| Agent | What it does | Key tools |
|---|---|---|
| **SqlAssistant** | Write, validate, format, and explain SQL queries | `validate_sql`, `format_sql`, `explain_query` |
| **SchemaAssistant** | Design and document DDL (CREATE TABLE, indexes) | `generate_create_table`, `suggest_indexes`, `describe_schema` |

Both agents share `validate_sql` and `format_sql` from `app/shared/sql_tools.py` (backed by [sqlglot](https://github.com/tobymao/sqlglot)).

### Infrastructure

Infrastructure is declared in `agentcore/agentcore.json` (the source of truth) and synthesized to CDK by `@aws/agentcore-cdk`. The project uses a **flat resource model** — runtimes, memories, credentials, gateways, and evaluators are independent top-level arrays; there is no binding in the schema. Renaming a resource destroys and recreates it.

```
agentcore/
├── agentcore.json        # Declarative resource config
├── aws-targets.json      # Deployment target (account 580776257674, us-east-2)
├── secrets/
│   └── dev.enc.yaml      # SOPS-encrypted secrets (committed to repo)
└── cdk/                  # Generated CDK project (do not edit directly)

app/
├── SqlAssistant/         # Strands agent + tools + tests
├── SchemaAssistant/      # Strands agent + tools + tests
└── shared/               # sql_tools.py shared by both agents

evals/                    # LLM-as-a-judge evaluator scripts
```

---

## Secrets & Environments

No plaintext secrets are stored in GitHub. The strategy is: **encrypt at rest in the repo, decrypt at deploy time, store at runtime in Secrets Manager**.

### How it works

1. **Encrypted at rest** — `agentcore/secrets/dev.enc.yaml` holds `LITELLM_API_KEY` and `LITELLM_BASE_URL` encrypted with [SOPS](https://github.com/getsops/sops) using a KMS key (`beac726e-bd4a-4857-863d-b9e0119d25d2`). The ciphertext is safe to commit.

2. **Decrypted in CI** — On push to `main`, the deploy job assumes the `GitHubActions-TrevorShowcase-Dev` IAM role via OIDC (no long-lived AWS credentials in GitHub). The role has KMS decrypt access, so `sops -d` can decrypt the file. Only the role ARN itself is stored as a GitHub secret.

3. **Pushed to Secrets Manager** — The CI job writes the decrypted JSON to the `TrevorShowcase/SqlAssistant/litellm` secret (creating it if it doesn't exist).

4. **Read at runtime** — Both agents receive `LITELLM_SECRET_ARN` as an environment variable. Their execution roles have `secretsmanager:GetSecretValue` on that ARN, and the agent process fetches the credentials on startup.

### Adding or rotating a secret

```bash
# Decrypt, edit, re-encrypt
sops agentcore/secrets/dev.enc.yaml
# Commit the updated .enc.yaml — CI will sync it to Secrets Manager on the next push to main
```

### Environments

| Environment | Trigger | AWS role |
|---|---|---|
| `dev` | Push to `main` | `GitHubActions-TrevorShowcase-Dev` |
| `staging` | Git tag (`v*`) + manual approval | `GitHubActions-TrevorShowcase-Stg` (via `AWS_ROLE_ARN_STG`) |

---

## Getting Started

### Prerequisites

- **Node.js** 20.x or later
- **Python 3.10+** and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- **AWS credentials** configured (`aws configure` or env vars)
- **agentcore CLI** — `npm install -g @aws/agentcore@0.22.0`
- **SOPS** — only needed if you will rotate secrets locally

### Local development

```bash
# Copy and populate local secrets (gitignored)
cp agentcore/.env.local.example agentcore/.env.local
# Fill in LITELLM_API_KEY and LITELLM_BASE_URL

agentcore dev   # hot-reload local agent
```

### Running tests

```bash
cd app/SqlAssistant && uv run pytest tests/ -v
cd app/SchemaAssistant && uv run pytest tests/ -v
```

### Deploying manually

```bash
agentcore validate          # check config before deploying
agentcore deploy --target default --yes
agentcore status            # confirm runtimes are active
```

---

## CLI Reference

| Command | Description |
|---|---|
| `agentcore dev` | Run agent locally with hot-reload |
| `agentcore deploy` | Deploy to AWS via CDK |
| `agentcore status` | Show deployment status |
| `agentcore invoke` | Invoke agent (local or deployed) |
| `agentcore logs` | Stream agent runtime logs |
| `agentcore traces list` | List recent traces |
| `agentcore eval` | Run evaluations |
| `agentcore validate` | Validate configuration |
| `agentcore add <resource>` | Add a resource (agent, memory, gateway, …) |
| `agentcore remove <resource>` | Remove a resource |
| `agentcore update` | Check for CLI updates |

---

## Lessons Learned

**SOPS + KMS is the right pattern for committing secrets.** Keeping encrypted secrets in the repo means a single source of truth and no out-of-band secret distribution. The tradeoff is that every developer who needs to rotate a secret must have KMS decrypt access — make sure that's scoped to the right IAM principals from the start.

**OIDC beats long-lived credentials everywhere.** Removing static AWS keys from GitHub eliminates an entire class of credential-leak risk. The setup cost (OIDC provider + trust policy) is a one-time 15-minute investment.

**The flat resource model is a double-edged sword.** `agentcore.json` is easy to reason about and diff, but renaming any resource will destroy and recreate it — which can cause downtime for deployed agents. Treat resource `name` fields as immutable identifiers from the moment you first deploy.

**Shared tools need to live in `app/shared/` from day one.** Duplicating `validate_sql` and `format_sql` into each agent first and then refactoring creates unnecessary churn. If two agents share logic, extract it before the first deploy.

**LiteLLM as a proxy adds flexibility but adds a hop.** Routing through VTS's LiteLLM instance means model swaps require no code changes, but it also means a latency floor and an extra failure mode. Log the model name from LiteLLM responses so traces stay interpretable when the underlying model changes.

---

## Documentation

- [AgentCore CLI](https://github.com/aws/agentcore-cli)
- [AgentCore CDK Constructs](https://github.com/aws/agentcore-l3-cdk-constructs)
- [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/)
- [Strands Agents](https://strandsagents.com)
- [SOPS](https://github.com/getsops/sops)
