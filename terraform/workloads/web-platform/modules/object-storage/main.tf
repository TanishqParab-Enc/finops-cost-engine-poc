resource "aws_s3_bucket" "assets" {
  bucket        = "${var.name_prefix}-assets"
  force_destroy = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-assets" })
}

resource "aws_s3_bucket_public_access_block" "assets" {
  bucket = aws_s3_bucket.assets.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "assets" {
  bucket = aws_s3_bucket.assets.id

  versioning_configuration {
    status = var.versioning_enabled ? "Enabled" : "Suspended"
  }
}

# Versioning retains every overwrite, so without expiry the bucket grows
# without bound - and S3 is billed per stored GB.
resource "aws_s3_bucket_lifecycle_configuration" "assets" {
  bucket     = aws_s3_bucket.assets.id
  depends_on = [aws_s3_bucket_versioning.assets]

  rule {
    id     = "expire-noncurrent-versions"
    status = var.versioning_enabled ? "Enabled" : "Disabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_expiration_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
