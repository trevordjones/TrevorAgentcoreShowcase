# AWS Resources

Account: `580776257674` | Region: `us-east-2`

---

## IAM

### OIDC Identity Provider

| Field | Value |
|---|---|
| Provider URL | `token.actions.githubusercontent.com` |
| ARN | `arn:aws:iam::580776257674:oidc-provider/token.actions.githubusercontent.com` |
| Audience | `sts.amazonaws.com` |

Pre-existing shared provider — not managed by this project.

---

### Role: `GitHubActions-TrevorShowcase-Dev`

CI/CD role assumed by GitHub Actions on push to `main` via OIDC (no static credentials).

**ARN:** `arn:aws:iam::580776257674:role/GitHubActions-TrevorShowcase-Dev`

**Attached policy:** `AdministratorAccess` — CDK requires broad permissions to create/update agent execution roles and CloudFormation stacks on first deploy. Scope down once the stack is stable.

**Trust policy:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::580776257674:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:trevordjones/TrevorAgentcoreShowcase:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

---

### Role: `AgentCore-TrevorShowcase--ApplicationAgentSqlAssist-ZwymjDXXRdjQ`

Execution role for the **SqlAssistant** AgentCore runtime. Managed by CDK — do not edit manually.

**ARN:** `arn:aws:iam::580776257674:role/AgentCore-TrevorShowcase--ApplicationAgentSqlAssist-ZwymjDXXRdjQ`

**Inline policy:** `ApplicationAgentSqlAssistantRuntimeExecutionRoleDefaultPolicy9EB8431F`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:CountTokens",
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*:580776257674:inference-profile/*",
        "arn:aws:bedrock:*::foundation-model/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:DescribeLogGroups",
        "xray:PutTelemetryRecords",
        "xray:PutTraceSegments"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:DescribeLogStreams",
        "logs:FilterLogEvents",
        "logs:GetLogEvents",
        "logs:PutLogEvents",
        "logs:PutResourcePolicy"
      ],
      "Resource": "arn:aws:logs:us-east-2:580776257674:log-group:/aws/bedrock-agentcore/runtimes/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:CreateConfigurationBundle",
        "bedrock-agentcore:DeleteConfigurationBundle",
        "bedrock-agentcore:GetConfigurationBundle",
        "bedrock-agentcore:GetConfigurationBundleVersion",
        "bedrock-agentcore:ListConfigurationBundleVersions",
        "bedrock-agentcore:ListConfigurationBundles",
        "bedrock-agentcore:UpdateConfigurationBundle"
      ],
      "Resource": "arn:aws:bedrock-agentcore:*:*:configuration-bundle/*"
    },
    {
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:us-east-2:580776257674:secret:TrevorShowcase/SqlAssistant/litellm*"
    }
  ]
}
```

---

### Role: `AgentCore-TrevorShowcase--ApplicationAgentSchemaAss-J36eAv0XY8nJ`

Execution role for the **SchemaAssistant** AgentCore runtime. Managed by CDK — do not edit manually.

**ARN:** `arn:aws:iam::580776257674:role/AgentCore-TrevorShowcase--ApplicationAgentSchemaAss-J36eAv0XY8nJ`

**Inline policy:** `ApplicationAgentSchemaAssistantRuntimeExecutionRoleDefaultPolicy2B383AAA`

Same permissions as SqlAssistant above — both agents read from the same Secrets Manager secret.

---

## Secrets Manager

### `TrevorShowcase/SqlAssistant/litellm`

LiteLLM credentials read at runtime by both SqlAssistant and SchemaAssistant.

| Field | Value |
|---|---|
| ARN | `arn:aws:secretsmanager:us-east-2:580776257674:secret:TrevorShowcase/SqlAssistant/litellm-CgLUC0` |
| Secret keys | `LITELLM_API_KEY`, `LITELLM_BASE_URL` |
| Source | Decrypted from `agentcore/secrets/dev.enc.yaml` by CI on each push to `main` |
| Consumers | SqlAssistant runtime (via `LITELLM_SECRET_ARN` env var), SchemaAssistant runtime |

---

## KMS

### SOPS Encryption Key

Used to encrypt `agentcore/secrets/dev.enc.yaml` at rest in the repository.

| Field | Value |
|---|---|
| ARN | `arn:aws:kms:us-east-2:580776257674:key/beac726e-bd4a-4857-863d-b9e0119d25d2` |
| Usage | SOPS envelope encryption for secrets committed to the repo |
| Key policy principals | `580776257674:root` (IAM-delegated), `PowerUserAccess`, `PlatformAdmin` |

The CI role (`GitHubActions-TrevorShowcase-Dev`) inherits decrypt access via the root account delegation in the key policy combined with its `AdministratorAccess` IAM policy.

---

## AgentCore Runtimes

Both agents are deployed as `CodeZip` runtimes under the `TrevorShowcase` project, target `default` (us-east-2).

| Agent | Network | Protocol | Python | Secret |
|---|---|---|---|---|
| SqlAssistant | PUBLIC | HTTP | 3.14 | `TrevorShowcase/SqlAssistant/litellm` |
| SchemaAssistant | PUBLIC | HTTP | 3.14 | `TrevorShowcase/SqlAssistant/litellm` |

Managed via `agentcore/agentcore.json` and deployed through CDK (`agentcore/cdk/`). CLI package: `@aws/agentcore` v0.22.0.
