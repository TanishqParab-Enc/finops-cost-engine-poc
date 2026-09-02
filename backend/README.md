# Backend Infrastructure

Terraform-managed AWS and GitHub infrastructure that the Shift-Left FinOps cost gate depends on.

Nothing here is created by hand in the AWS console except AWS credentials themselves.

---

## What this provisions

| Component | Where |
|---|---|
| S3 bucket for Terraform remote state (versioned, encrypted, private) | `bootstrap/` |
| S3 **native** state locking (`use_lockfile`) | every `backend.hcl` |
| GitHub OIDC identity provider in IAM | `environments/<env>/` |
| GitHub Actions **plan** role (read-only + Bedrock) | `environments/<env>/` |
| GitHub Actions **deploy** role (write, environment-gated) | `environments/<env>/` |
| Scoped `bedrock:InvokeModel` for the AI explanation layer | `environments/<env>/` |
| GitHub environments, required reviewers, non-secret variables | `github/` |

No static AWS access keys are created anywhere. GitHub Actions authenticates purely via OIDC.

---

## Layout

```
backend/
├── bootstrap/                  # LOCAL state - creates the state bucket itself
├── modules/
│   ├── terraform-state/        # S3 state bucket (+ optional legacy DynamoDB)
│   ├── github-oidc/            # OIDC provider, create-or-reuse
│   ├── github-actions-roles/   # plan + deploy roles, trust, Bedrock policy
│   ├── github-environment/     # GitHub environment, reviewers, variables
│   └── finops-environment/     # composes the AWS side for one environment
├── environments/
│   ├── dev/                    # AWS only - no GitHub token needed
│   ├── staging/
│   └── prod/
└── github/                     # GitHub environments + variables (separate state)
```

`environments/*/main.tf` are identical by design. **Only `terraform.tfvars` differs.** Adding `qa` or `uat` means copying an environment directory and editing its tfvars — never editing module code.

### State boundaries

Each layer has its own state file, so a mistake in one cannot corrupt another:

| Layer | State key |
|---|---|
| bootstrap | local `terraform.tfstate` (gitignored) |
| dev | `finops-poc/dev/terraform.tfstate` |
| staging | `finops-poc/staging/terraform.tfstate` |
| prod | `finops-poc/prod/terraform.tfstate` |
| github | `finops-poc/github/terraform.tfstate` |

---

## State locking

Terraform 1.10+ locks S3 state natively using conditional writes. **DynamoDB locking is deprecated** and is not used.

```hcl
terraform {
  backend "s3" {
    bucket       = "finops-poc-tfstate-<account-id>"
    key          = "finops-poc/dev/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true      # native S3 locking
  }
}
```

A DynamoDB table can still be created via `enable_legacy_dynamodb_lock = true` in the bootstrap layer, but **only** to migrate a pre-1.10 backend. New environments must not use it.

---

## First-time setup

### 1. Configure AWS credentials

```bash
aws sts get-caller-identity      # confirm the right account
```

### 2. Bootstrap the state bucket

This layer uses **local state** because Terraform cannot store state in a bucket that does not exist yet.

```bash
cd backend/bootstrap
cp terraform.tfvars.example terraform.tfvars   # edit if needed
terraform init
terraform plan  -var-file=terraform.tfvars     # expect "N to add, 0 to change, 0 to destroy"
terraform apply -var-file=terraform.tfvars
terraform output state_bucket_name
```

Keep the local `backend/bootstrap/terraform.tfstate` safe. It is gitignored. If lost, the bucket can be re-imported:

```bash
terraform import module.terraform_state.aws_s3_bucket.state <bucket-name>
```

### 3. Apply `dev` — this also creates the OIDC provider

Only one GitHub OIDC provider may exist per AWS account, so exactly one environment creates it.

```bash
cd ../environments/dev
cp backend.hcl.example        backend.hcl          # set the bucket name
cp terraform.tfvars.example   terraform.tfvars     # set owner/repo/account id

terraform init -backend-config=backend.hcl
terraform plan  -var-file=terraform.tfvars         # REVIEW before applying
terraform apply -var-file=terraform.tfvars

terraform output github_oidc_provider_arn
terraform output plan_role_arn
terraform output deploy_role_arn
```

### 4. Apply `staging` and `prod` — reusing that provider

In each of their `terraform.tfvars`:

```hcl
create_oidc_provider       = false
existing_oidc_provider_arn = "<value from step 3>"
```

Then the same three commands.

### 5. Configure GitHub

```bash
cd ../../github
cp backend.hcl.example      backend.hcl
cp terraform.tfvars.example terraform.tfvars   # paste role ARNs from steps 3-4

export GITHUB_TOKEN=<token with repo scope>
terraform init -backend-config=backend.hcl
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

### 6. Set the Infracost secret (out-of-band)

Secrets are deliberately **not** managed by Terraform — the GitHub provider stores them in plaintext in state.

```bash
gh secret set INFRACOST_API_KEY --repo <owner>/<repo>
```

Get the value from https://dashboard.infracost.io → Org Settings → **CLI tokens**.

---

## Importing existing resources

Verified on 2026-09-02: account `024125831628` had **no** OIDC provider, finops roles, state bucket or DynamoDB tables, so everything is created fresh. If you run this in an account where they already exist, import rather than recreate:

```bash
# OIDC provider
terraform import module.backend.module.github_oidc.aws_iam_openid_connect_provider.github[0] \
  arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com

# IAM roles
terraform import module.backend.module.github_actions_roles.aws_iam_role.plan   <role-name>
terraform import module.backend.module.github_actions_roles.aws_iam_role.deploy <role-name>

# State bucket (bootstrap layer)
terraform import module.terraform_state.aws_s3_bucket.state <bucket-name>

# GitHub environment (github layer)
terraform import 'module.environments["production"].github_repository_environment.this' \
  <repo>:production
```

Alternatively set `create_oidc_provider = false` and pass `existing_oidc_provider_arn`.

Check what exists first:

```bash
aws iam list-open-id-connect-providers
aws iam list-roles --query "Roles[?contains(RoleName,'finops')].RoleName"
aws s3api list-buckets --query "Buckets[].Name"
```

---

## Least privilege

### Plan role

Assumable only from `repo:<owner>/<repo>:pull_request` and `repo:<owner>/<repo>:ref:refs/heads/<branch>`.

| Permission | Why |
|---|---|
| `ec2:Describe*` (explicit list) | `terraform plan` refreshes state. Describe actions do not support resource-level scoping. |
| `sts:GetCallerIdentity` | The AWS provider calls this on startup. |
| `s3:GetObject/PutObject/DeleteObject` on its own state prefix | Native S3 locking writes and deletes a `.tflock` object, so even `plan` needs write access **to the lock file**. |
| `bedrock:InvokeModel` on one inference profile | The AI explanation layer. |

No `AdministratorAccess`. Variable validation actively rejects it.

### Deploy role

Assumable **only** from `repo:<owner>/<repo>:environment:<environment>`, so GitHub's required reviewers gate every use of it.

Write actions are enumerated explicitly and constrained with `aws:RequestedRegion`.

Extend either role without editing modules:

```hcl
extra_plan_actions   = ["rds:DescribeDBInstances"]
extra_deploy_actions = ["rds:CreateDBInstance"]
```

### Bedrock permission

The application invokes a **cross-region inference profile**, not a bare model ID. Per [AWS documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html):

> When you specify an inference profile in the `Resource` field, you must **also** specify the foundation model in **each Region** associated with it.

`us.anthropic.claude-haiku-4-5-20251001-v1:0` routes to **us-east-1, us-east-2 and us-west-2**, so the generated policy is:

```json
{
  "Statement": [
    {
      "Sid": "InvokeInferenceProfile",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:us-east-1:<account>:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0"
    },
    {
      "Sid": "InvokeFoundationModelsViaProfileOnly",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"
      ],
      "Condition": {
        "StringLike": {
          "bedrock:InferenceProfileArn": "arn:aws:bedrock:us-east-1:<account>:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0"
        }
      }
    }
  ]
}
```

The condition means the foundation models can be reached **only** through this profile, not directly.

Regenerate the region list if you change models:

```bash
aws bedrock get-inference-profile \
  --inference-profile-identifier us.anthropic.claude-haiku-4-5-20251001-v1:0
```

> Claude 3 Haiku is deprecated on Bedrock and returns `AccessDenied` for inactive accounts. Newer Claude models reject bare model IDs with *"Retry with an inference profile"*. Use the profile ID.

---

## Two independent gates

These are separate controls and neither substitutes for the other:

| Gate | Type | Where |
|---|---|---|
| **FinOps cost threshold** | Automatic, deterministic | `config/finops-policy.yaml`, evaluated by the cost engine |
| **Production approval** | Manual, human | GitHub environment required reviewers |

A PR under the cost threshold still requires human approval to deploy to production. A PR over the threshold is blocked before it ever reaches that point.

```
PR → plan → Infracost → threshold → PASS/FAIL
                                      │
                                      PASS → cost lock → production environment → reviewer approval → apply
                                      FAIL → build blocked, no lock, peer review required
```

---

## GitHub environment requirements

Required reviewers on environments need:

- **Public repositories** — available on all plans
- **Private repositories** — GitHub **Pro, Team or Enterprise**

If you are on a private repo with GitHub Free, `github_repository_environment` will apply but protection rules are silently ignored. Either make the repo public, upgrade, or rely on branch protection instead.

Reviewer IDs are numeric, not usernames:

```bash
gh api /users/<login> --jq .id          # user ID
gh api /orgs/<org>/teams/<slug> --jq .id  # team ID
```

---

## Adding a new environment

```bash
cp -r backend/environments/dev backend/environments/qa
cd backend/environments/qa
```

Edit `terraform.tfvars`:

```hcl
environment                = "qa"
create_oidc_provider       = false
existing_oidc_provider_arn = "<existing arn>"
```

Edit `backend.hcl`:

```hcl
key = "finops-poc/qa/terraform.tfstate"
```

Then `terraform init -backend-config=backend.hcl && terraform apply -var-file=terraform.tfvars`.

No module code changes.

---

## Validation

```bash
terraform fmt -recursive
terraform validate            # in each layer
terraform plan -var-file=terraform.tfvars
```

A helper avoids PowerShell native-argument quirks on Windows:

```bash
python scripts/backend_tf.py bootstrap
python scripts/backend_tf.py dev --backend-config=backend.hcl
```

Before every apply, confirm:

- [ ] `terraform fmt -recursive` produces no changes
- [ ] `terraform validate` succeeds
- [ ] Plan shows **`0 to destroy`**
- [ ] OIDC trust `sub` is scoped to your repo, never `*`
- [ ] No `AdministratorAccess` anywhere
- [ ] Bedrock resources match `get-inference-profile` output
- [ ] State bucket name and region are correct
- [ ] No secret values appear in outputs

---

## Outputs

Safe to expose. No secrets, tokens or credentials are ever output.

| Output | Purpose |
|---|---|
| `terraform_state_bucket` | Backend config |
| `terraform_state_key` | Backend config |
| `plan_role_arn` | GitHub variable `AWS_PLAN_ROLE_ARN` |
| `deploy_role_arn` | GitHub variable `AWS_DEPLOY_ROLE_ARN` |
| `github_oidc_provider_arn` | Pass to other environments |
| `github_environment_name` | Workflow `environment:` key |
| `plan_trust_subjects` / `deploy_trust_subjects` | Audit the trust scope |

---

## Never commit

Enforced by `backend/.gitignore`:

`*.tfstate`, `*.tfstate.*`, `.terraform/`, `terraform.tfvars`, `backend.hcl`, `*.tfplan`, `plan.json`

Only `*.example` files are tracked.
