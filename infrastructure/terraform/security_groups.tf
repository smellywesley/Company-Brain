resource "aws_security_group" "alb" {
  name        = "company-brain-alb-sg-${var.environment}"
  description = "Controls ingress and egress to the Load Balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    protocol    = "tcp"
    from_port   = 80
    to_port     = 80
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "company-brain-alb-sg-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_security_group" "backend" {
  name        = "company-brain-backend-sg-${var.environment}"
  description = "Allows ingress only from the ALB on port 8000"
  vpc_id      = aws_vpc.main.id

  ingress {
    protocol        = "tcp"
    from_port       = 8000
    to_port         = 8000
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "company-brain-backend-sg-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_security_group" "worker" {
  name        = "company-brain-worker-sg-${var.environment}"
  description = "No ingress needed for celery background worker task"
  vpc_id      = aws_vpc.main.id

  # Background tasks don't listen on any ports
  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "company-brain-worker-sg-${var.environment}"
    Environment = var.environment
  }
}
