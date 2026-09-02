# Terraform state backend infrastructure.
#
# Terraform 1.10+ supports native S3 state locking via conditional writes
# (`use_lockfile = true` in the backend block), which is why no DynamoDB table
# is created by default. DynamoDB-based locking is deprecated.

locals {
  bucket_name = coalesce(var.bucket_name, "${var.project_name}-tfstate-${var.aws_account_id}")

  tags = merge(
    {
      Project   = var.project_name
      ManagedBy = "Terraform"
      Purpose   = "Terraform remote state storage"
    },
    var.tags,
  )
}

resource "aws_s3_bucket" "state" {
  bucket = local.bucket_name
  tags   = local.tags

  # State loss is unrecoverable. Removing this guard is a deliberate,
  # documented action - see backend/README.md.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn == null ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = var.kms_key_arn != null
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Expire non-current state versions so the bucket does not grow without bound,
# while still retaining enough history to recover from a bad apply.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket     = aws_s3_bucket.state.id
  depends_on = [aws_s3_bucket_versioning.state]

  rule {
    id     = "expire-noncurrent-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "state" {
  # Reject any request not using TLS.
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # Reject uploads that are not server-side encrypted.
  statement {
    sid    = "DenyUnencryptedObjectUploads"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.state.arn}/*"]

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = var.kms_key_arn == null ? ["AES256", "aws:kms"] : ["aws:kms"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket     = aws_s3_bucket.state.id
  policy     = data.aws_iam_policy_document.state.json
  depends_on = [aws_s3_bucket_public_access_block.state]
}

# ---------------------------------------------------------------------------
# DEPRECATED: DynamoDB lock table.
#
# Only for migrating environments that still use `dynamodb_table` in their
# backend block. New environments must use `use_lockfile = true` instead.
# ---------------------------------------------------------------------------
resource "aws_dynamodb_table" "legacy_lock" {
  count = var.enable_legacy_dynamodb_lock ? 1 : 0

  name         = coalesce(var.legacy_dynamodb_table_name, "${local.bucket_name}-lock")
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = merge(local.tags, {
    Purpose    = "DEPRECATED Terraform state locking - use S3 use_lockfile instead"
    Deprecated = "true"
  })
}
