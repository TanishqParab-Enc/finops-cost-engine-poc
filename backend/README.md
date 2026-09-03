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
│   └── prod/
└── github/                     # GitHub environments + variables (separate state)
```

`environments/*/main.tf` are identical by design. **Only `terraform.tfvars` differs.** Adding `staging`, `qa` or `uat` means copying an environment directory and editing its tfvars — never editing module code. (A `staging` tier existed here until 2026-09-03; it was dropped because the shared-secret design below meant its IAM roles were created but never actually used - see "Why only two tiers".)

### State boundaries

Each layer has its own state file, so a mistake in one cannot corrupt another:

| Layer | State key |
|---|---|
| bootstrap | local `terraform.tfstate` (gitignored) |
| dev | `finops-poc/dev/terraform.tfstate` |
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

### 4. Apply `prod` — reusing that provider

In its `terraform.tfvars`:

```hcl
create_oidc_provider       = false
existing_oidc_provider_arn = "<value from step 3>"
```

Then the same three commands.

### 5. Configure GitHub

```bash
cd ../../github
cp backend.hcl.example      backend.hcl
cp terraform.tfvars.example terraform.tfvars   # paste role ARNs from step 3-4

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

| Gate | Type | Where | Enforced here? |
|---|---|---|---|
| **FinOps cost threshold** | Automatic, deterministic | `config/finops-policy.yaml` | Yes |
| **Production approval** | Human | GitHub environment | **No** — see the verified limitation above; currently manual-dispatch only |

A PR under the cost threshold still requires a deliberate manual dispatch to reach production. A PR over the threshold is blocked before it ever gets there.

```
PR → plan → Infracost → threshold → PASS/FAIL
                                      │
                                      PASS → cost lock → manual dispatch + typed confirmation → apply
                                      FAIL → build blocked, no lock, peer review required
```

---

## Production approval — VERIFIED LIMITATION

**Required reviewers do not work on this repository.** This was tested against the live API on 2026-09-02, not assumed:

```bash
$ gh api --method PUT /repos/TanishqParab-Enc/finops-cost-engine-poc/environments/protection-test \
    --input '{"reviewers":[{"type":"User","id":209082352}],"prevent_self_review":true}'

HTTP 422
"Failed to create the environment protection rule. Please ensure the billing
 plan supports the required reviewers protection rule."
```

The repository is **private** and owned by a **personal account**. Required reviewers on environments need GitHub **Pro, Team or Enterprise** for private repositories.

### What does and does not work here

| Capability | Status | Consequence |
|---|---|---|
| Create environment | Works | `protection_rules: []` |
| Environment-scoped OIDC subject | Works | Deploy role trust **is** enforced by AWS |
| Deployment branch policies | Works | Branch restriction is enforced |
| **Required reviewers / manual approval** | **HTTP 422** | **Not enforced** |

So `environment: production` is still declared in `backend-apply.yml` — it scopes the deploy role's OIDC trust to `repo:<owner>/<repo>:environment:production`, which AWS genuinely enforces — but **it does not gate the apply behind a human**.

### The actual production gate in use

Because approval cannot be enforced, production apply is **not reachable from a push**. It requires a deliberate human action:

1. Run `Backend Terraform Apply` manually via **workflow_dispatch**
2. Select `environment: prod`
3. Type `prod` into the **confirm** input

A mismatched or empty confirmation fails the job before any AWS credentials are used.

```yaml
if: github.event_name == 'workflow_dispatch' && inputs.environment == 'prod'
```

No environment applies automatically on a push to `main` — see "GitHub Actions workflow" below. Dev's typed
confirm is optional; prod's is required.

### To get real approval enforcement

Any one of these, after which the existing `environment: production` starts enforcing with no code change:

| Option | Cost |
|---|---|
| Make the repository public | Free |
| Upgrade to GitHub Pro | ~$4/user/month |
| Move to a GitHub Team organization | ~$4/user/month |

Then set reviewers in `backend/github/terraform.tfvars`:

```hcl
production = {
  reviewer_user_ids   = [209082352]
  prevent_self_review = true
}
```

and remove the `workflow_dispatch`-only restriction on the `prod` job.

> Until then, **do not describe production apply as "approval gated"**. It is *manual-dispatch gated*, which is weaker: it proves intent but not peer review.

---

## GitHub Actions workflow

One workflow handles the whole backend lifecycle: [.github/workflows/backend.yml](../.github/workflows/backend.yml)

| Event | What runs |
|---|---|
| PR touching `backend/**` | static checks → plan (both environments) → PR comment |
| Push to `main` | static checks → plan (both environments, read-only) — **no apply** |
| Manual dispatch | static checks → plan → apply **only** the chosen environment |

```
preflight ──► plan ──► apply-dev   (workflow_dispatch, environment == dev)
(no creds)   (read-only ──► apply-prod  (workflow_dispatch, environment == prod
              plan role)                                     + typed confirm)
```

Each `apply-*` job is independent — none `needs:` another apply job. Choosing `prod` in
workflow_dispatch runs plan then applies **only** prod; dev is untouched in that run. A push to
`main` only re-plans both environments for visibility and never applies anything, so merging a
PR can never trigger an unattended change in AWS.

### Why one workflow

Plan and apply share the same inputs, the same rendered tfvars and the same ordering. Splitting them meant duplicating all of that and losing the guarantee that **the plan you reviewed is the plan that gets applied**. Here every apply is preceded by a plan in the same run.

### The bootstrap guard

The `preflight` job runs `fmt -check` and `validate` **without any AWS credentials**, then checks whether bootstrap has been completed:

| Required | Type |
|---|---|
| `AWS_PLAN_ROLE_ARN` | secret |
| `TF_STATE_BUCKET` | variable |
| `AWS_OIDC_PROVIDER_ARN` | variable |

If any are missing, plan and apply are **skipped with an explanatory summary** rather than failing with `Could not load credentials from any providers`. This is the expected state before bootstrap has been run.

### Safety properties

| Property | How it is enforced |
|---|---|
| Plans cannot apply | The plan job assumes the **read-only** plan role — apply is impossible, not just omitted |
| PRs never apply | `github.event_name != 'pull_request'` on every apply job |
| Push never applies | Every apply job requires `github.event_name == 'workflow_dispatch'` — a push only plans |
| No cross-environment cascade | Each apply job is gated only by `inputs.environment == '<env>'`; apply jobs do not depend on each other |
| Applied plan == reviewed plan | Plans to a file, then applies **that saved file** |
| No accidental deletion | The composite action **aborts** if the plan would destroy any resource |
| No concurrent state writes | `concurrency: backend-terraform-<ref>` |
| No static AWS keys | OIDC only |

### Two OIDC gotchas that will lock CI out of AWS

Both were hit for real on 2026-09-02 and are now handled in code. Read this before changing the trust policy or the tfvars rendering.

**1. GitHub sends immutable subject claims containing numeric IDs.**

Decoding a real token from this repo gave:

```
sub : repo:TanishqParab-Enc@209082352/finops-cost-engine-poc@1353830250:ref:refs/heads/main
```

not the classic `repo:owner/repo:ref:refs/heads/main`. A trust policy allowing only the classic form fails every assume-role with:

```
Could not assume role with OIDC: Not authorized to perform sts:AssumeRoleWithWebIdentity
```

The module trusts **both** forms. Supply `github_owner_id` and `github_repository_id`; CI derives them from `github.repository_owner_id` and `github.repository_id`. Check your repo's format with:

```bash
gh api /repos/<owner>/<repo>/actions/oidc/customization/sub
```

**2. Only one environment may own the OIDC provider.**

If CI renders `create_oidc_provider = false` while an environment's state owns it, Terraform plans to **destroy the provider CI authenticates with** — a self-inflicted lockout that also requires local credentials to repair.

CI derives this from `OIDC_OWNER_ENVIRONMENT` (default `dev`). The composite action's destroy guard caught exactly this case before it applied:

```
X Plan would destroy 1 resource(s) in dev. Apply aborted.
  # module.backend.module.github_oidc.aws_iam_openid_connect_provider.github[0] will be destroyed
```

**3. A single shared deploy role must trust every GitHub environment it will assume-role from.**

This design uses one repo-level `AWS_DEPLOY_ROLE_ARN` secret for every environment (rather than a separate
role per environment), so the deploy role's trust policy must list every GitHub Actions `environment:`
subject it will ever be assumed from, not just the one that created it. Hit for real on 2026-09-02: the role
was created by the `dev` environment folder with `github_environment_name = "dev"`, so its trust policy only
allowed `...:environment:dev`. `Apply staging` then failed with (staging existed at the time; see "Why only
two tiers" below for why it was later dropped):

```
Not authorized to perform sts:AssumeRoleWithWebIdentity
```

Fixed by `additional_deploy_environments` on the `github-actions-roles` module: when
`enable_backend_self_management = true`, `finops-environment` passes the GitHub environment name(s) the
current environment does *not* own (e.g. dev's module call passes `["production"]`), and the module unions
them with its own `github_environment_name` before building `deploy_subjects`. The deploy role's trust
policy therefore lists `environment:dev` and `environment:production` simultaneously — the same "make the
IAM scope project-wide because the CI identity already is" pattern used for the state-access fix above.

**4. The deploy role needs `iam:ListInstanceProfilesForRole` to delete a role, not just to create one.**

Hit for real on 2026-09-03 while destroying staging's roles: `terraform destroy` removed every policy and
attachment successfully, then failed on the role itself:

```
Error: deleting IAM Role (finops-poc-staging-deploy-role): reading IAM Instance Profiles for Role: AccessDenied:
... not authorized to perform: iam:ListInstanceProfilesForRole ...
```

The AWS provider checks a role for attached instance profiles before deleting it — a read call, but a
different one than any of the `Get`/`List` actions already granted. Added to `ManageBackendIamWrite` alongside
the other role-lifecycle actions.

### Why only two tiers (dev + prod)

This started as dev/staging/prod, matching a typical enterprise promotion pipeline. It was collapsed to
dev + prod on 2026-09-03 after applying staging for real exposed why the extra tier added by that name
specifically wasn't earning its keep **in this design**:

- Every environment's `finops-environment` module creates its **own** plan/deploy role pair, but
  `AWS_PLAN_ROLE_ARN`/`AWS_DEPLOY_ROLE_ARN` are single repo-level secrets. Only the ARNs from whichever
  environment's roles those secrets point at (dev's) are ever actually assumed. Applying staging created
  `finops-poc-staging-plan-role`/`finops-poc-staging-deploy-role` in AWS, but they sat unused — confirmed via
  `aws iam list-roles` before they were destroyed.
- Required-reviewer approval — the one thing that would have made "staging" meaningfully different from
  "prod" as a promotion gate — is unavailable on this repo (see the HTTP 422 limitation above). Without it,
  prod only differs from any other environment by a typed `confirm` string, which staging could have carried
  equally well.
- With one AWS account and one shared deploy identity, the three tiers gave state-file isolation and a
  distinct name in the run history, but no real permission or blast-radius isolation beyond that.

The alternative that *would* have kept 3 real tiers is per-environment GitHub Environment secrets (so
staging's job actually assumes staging's own role) instead of repo-level secrets — a valid, more "textbook"
design, deliberately not chosen here to keep the CI configuration simpler for a two-tier POC. Re-introducing
a third tier (or per-environment secrets) later is a matter of copying `environments/dev/` again, not a
module change — see `environments/*/main.tf` above.

### Backend self-management and privilege escalation

Because the workflow manages the backend layer, the roles need IAM permissions. IAM write is inherently privilege-adjacent, so:

- Deploy-role IAM actions are scoped to `arn:aws:iam::<acct>:role/<project>-*` and `.../policy/<project>-*`, plus the single GitHub OIDC provider ARN
- An explicit **`Deny`** blocks `UpdateAssumeRolePolicy`, `PutRolePolicy`, `AttachRolePolicy`, `DeleteRole` and friends on the plan and deploy roles themselves — Deny beats Allow, so the role cannot widen its own permissions
- Set `enable_backend_self_management = false` to remove all IAM permissions and run the backend layer only from a workstation

### Required repository configuration

tfvars are not committed, so CI renders them from repository variables.

| Type | Name | Example |
|---|---|---|
| Secret | `AWS_PLAN_ROLE_ARN` | `arn:aws:iam::<acct>:role/finops-poc-dev-plan-role` |
| Secret | `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::<acct>:role/finops-poc-dev-deploy-role` |
| Secret | `INFRACOST_API_KEY` | Infracost CLI token |
| Variable | `TF_STATE_BUCKET` | `finops-poc-tfstate-<acct>` |
| Variable | `TF_STATE_KEY_PREFIX` | `finops-poc` |
| Variable | `PROJECT_NAME` | `finops-poc` |
| Variable | `AWS_OIDC_PROVIDER_ARN` | `arn:aws:iam::<acct>:oidc-provider/token.actions.githubusercontent.com` |
| Variable | `FINOPS_BEDROCK_MODEL` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Variable | `BEDROCK_INFERENCE_PROFILE_ARN` | `arn:aws:bedrock:us-east-1:<acct>:inference-profile/us.anthropic...` |
| Variable | `BEDROCK_FOUNDATION_MODEL_ARNS` | JSON array — see below |

`BEDROCK_FOUNDATION_MODEL_ARNS` is injected verbatim as HCL, so it must be a valid JSON array:

```json
["arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0","arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0","arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"]
```

### Bootstrap stays out of CI, deliberately

`bootstrap/` is **never** run by GitHub Actions. It creates the S3 state bucket *and* the OIDC provider and IAM roles that the workflow itself authenticates with — CI cannot create its own credentials. Run it once, locally, with human AWS credentials.

```
bootstrap (local, once)
   └─► state bucket + OIDC provider + IAM roles
          └─► set GitHub secrets/variables
                 └─► backend.yml can authenticate
```

---

## Destroying backend infrastructure

Tearing down an environment's backend infrastructure is a **separate workflow**: [.github/workflows/backend-destroy.yml](../.github/workflows/backend-destroy.yml). It is never part of `backend.yml` and never runs from a push or a PR — destroying infrastructure is deliberate, not incidental.

### Trigger it

Actions → **Backend Terraform Destroy** → Run workflow, then fill in:

| Input | Required | Value |
|---|---|---|
| `environment` | Yes | `dev` or `prod` |
| `confirm` | Yes | Type **`destroy-<environment>`** exactly, e.g. `destroy-dev` |
| `confirm_oidc_impact` | Only if this environment owns the OIDC provider | Type **`yes-lock-out-all-environments`** exactly |

A mismatched or missing confirmation fails the job before any AWS credentials are used.

### Why the second confirmation exists

The environment named by the repo variable `OIDC_OWNER_ENVIRONMENT` (default `dev`) is the only one whose Terraform state owns the GitHub OIDC provider. Destroying it destroys the provider **every environment authenticates through** — confirmed for real on 2026-09-02, where a plan showed:

```
# module.backend.module.github_oidc.aws_iam_openid_connect_provider.github[0] will be destroyed
```

Destroying the OIDC-owning environment without realizing it would lock every environment out of AWS simultaneously, recoverable only by re-running bootstrap and re-applying that environment locally. The extra confirmation makes that impact impossible to trigger by accident.

### Safety properties

| Property | How it is enforced |
|---|---|
| Never automatic | The only trigger is `workflow_dispatch` — no `push`, no `pull_request` |
| Cannot fat-finger the environment | `confirm` must equal `destroy-<environment>` exactly |
| Cannot accidentally lock out all environments | Separate typed phrase, required only when it matters |
| Plan is reviewed before it runs | Full `terraform plan -destroy` posted to the job summary and uploaded as an artifact |
| Plan must be destroy-only | The action fails if the plan contains anything other than `delete`/`no-op` — catches tfvars misconfiguration before it can create or modify instead of tearing down |
| Applied plan == reviewed plan | Applies the saved `destroy.tfplan`, not a fresh plan |
| Cannot race an apply | Shares the `backend-terraform-<ref>` concurrency group with `backend.yml` |
| Production still scoped | Uses the same `environment: production` used by apply, so the deploy role's OIDC trust is unaffected |
| Bootstrap and GitHub layers untouched | Only acts on `backend/environments/<env>` — the state bucket (`prevent_destroy`) and `backend/github` are never in scope |

### What happens to the state file

`backend-destroy.yml` runs `terraform destroy` against the environment's existing state key (e.g.
`finops-poc/prod/terraform.tfstate` in the state bucket). Destroy removes the real AWS resources **and**
rewrites that state file to reflect zero managed resources — but it does not delete the state *object* from
S3. The object stays at the same key, now representing an empty state, and the bucket itself is a separate
resource (created in `bootstrap/`, protected by `prevent_destroy`) that `backend-destroy.yml` never touches.

Re-applying later — via `backend.yml`'s `workflow_dispatch`, any time after — reads that same (now empty)
state key and creates the resources fresh, exactly like the original first-time apply. No manual state
cleanup or recovery step is needed for a normal (non-OIDC-owning) environment.

The one exception is destroying the `OIDC_OWNER_ENVIRONMENT` (default `dev`): that also destroys the GitHub
OIDC provider every environment authenticates through. The S3 bucket is untouched (see above), so bootstrap
does **not** need to be rerun, but:

1. Re-apply that same environment locally (with human AWS credentials, since CI can no longer authenticate)
   to recreate the OIDC provider and the plan/deploy roles.
2. Reset `AWS_PLAN_ROLE_ARN`, `AWS_DEPLOY_ROLE_ARN` and `AWS_OIDC_PROVIDER_ARN` (GitHub secrets/variables) to
   the newly-created ARNs — they are regenerated with new resource IDs, not restored to their old values.
3. Only then will `backend.yml` be able to authenticate again for any environment.

Verified locally with a real `terraform plan -destroy` against the applied `dev` environment: `Plan: 0 to add, 0 to change, 10 to destroy` — clean, destroy-only, plan discarded without applying.

### What it does not tear down

| Layer | How to destroy it |
|---|---|
| `bootstrap` (state bucket) | Manually, locally: remove `prevent_destroy`, then `terraform destroy -var-file=terraform.tfvars` |
| `github` (environments/variables) | Manually, locally: `terraform destroy -var-file=terraform.tfvars` |

Both are rare, deliberately manual operations outside CI.

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
