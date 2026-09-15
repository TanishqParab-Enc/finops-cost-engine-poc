resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-vpc" })
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-igw" })
}

# Three tiers: public (ALB/NAT), app (storefront + workers), data (RDS/Redis).
# The data tier has no route to the internet at all.
resource "aws_subnet" "public" {
  count = var.az_count

  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-public-${count.index}", Tier = "public" })
}

resource "aws_subnet" "app" {
  count = var.az_count

  vpc_id            = aws_vpc.main.id
  cidr_block        = var.app_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = merge(var.tags, { Name = "${var.name_prefix}-app-${count.index}", Tier = "application" })
}

resource "aws_subnet" "data" {
  count = var.az_count

  vpc_id            = aws_vpc.main.id
  cidr_block        = var.data_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = merge(var.tags, { Name = "${var.name_prefix}-data-${count.index}", Tier = "data" })
}

# Each NAT gateway bills hourly plus per-GB processed, which makes
# nat_gateway_count one of the sharpest cost levers in this workload.
resource "aws_eip" "nat" {
  count  = var.nat_gateway_count
  domain = "vpc"

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat-eip-${count.index}" })
}

resource "aws_nat_gateway" "main" {
  count = var.nat_gateway_count

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index % var.az_count].id

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat-${count.index}" })

  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-rt-public" })
}

resource "aws_route_table_association" "public" {
  count = var.az_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# One app route table per AZ so each can egress via its own NAT when two are
# provisioned; with a single NAT they all share it.
resource "aws_route_table" "app" {
  count = var.az_count

  vpc_id = aws_vpc.main.id

  dynamic "route" {
    for_each = var.nat_gateway_count > 0 ? [1] : []
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.main[count.index % var.nat_gateway_count].id
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-rt-app-${count.index}", Tier = "application" })
}

resource "aws_route_table_association" "app" {
  count = var.az_count

  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = aws_route_table.app[count.index].id
}

# Deliberately has no default route: the data tier is reachable only from
# inside the VPC and cannot reach the internet in either direction.
resource "aws_route_table" "data" {
  vpc_id = aws_vpc.main.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-rt-data", Tier = "data" })
}

resource "aws_route_table_association" "data" {
  count = var.az_count

  subnet_id      = aws_subnet.data[count.index].id
  route_table_id = aws_route_table.data.id
}

# -- security groups ---------------------------------------------------------
# Least privilege is expressed as a chain: internet -> alb -> app -> data.
# Nothing in the data tier accepts traffic from anywhere except the tier that
# actually needs it, and no rule uses 0.0.0.0/0 except public ALB ingress.

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb-sg"
  description = "Public ingress to the storefront load balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from the internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Forward to the storefront tier"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-alb-sg" })
}

resource "aws_security_group" "app" {
  name        = "${var.name_prefix}-app-sg"
  description = "Storefront instances: ingress only from the load balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTP from the load balancer only"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "Outbound to AWS services and the data tier"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-app-sg" })
}

# Workers take no inbound traffic at all - they poll SQS outbound.
resource "aws_security_group" "worker" {
  name        = "${var.name_prefix}-worker-sg"
  description = "Background workers: no inbound, outbound only"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "Poll SQS and reach the data tier"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-worker-sg" })
}

resource "aws_security_group" "database" {
  name        = "${var.name_prefix}-db-sg"
  description = "PostgreSQL reachable only from the storefront and worker tiers"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from the storefront tier"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  ingress {
    description     = "PostgreSQL from the worker tier"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.worker.id]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-db-sg" })
}

# Only the storefront caches; workers write through the database.
resource "aws_security_group" "cache" {
  name        = "${var.name_prefix}-cache-sg"
  description = "Redis reachable only from the storefront tier"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis from the storefront tier"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-cache-sg" })
}
