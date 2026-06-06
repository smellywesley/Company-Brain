resource "aws_ecs_cluster" "main" {
  name = "company-brain-cluster-${var.environment}"

  tags = {
    Name        = "company-brain-ecs-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/company-brain-backend-${var.environment}"
  retention_in_days = 7

  tags = {
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/company-brain-worker-${var.environment}"
  retention_in_days = 7

  tags = {
    Environment = var.environment
  }
}

# ── Backend Task Definition (FastAPI) ──────────────────────────────────────
resource "aws_ecs_task_definition" "backend" {
  family                   = "cb-backend-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "backend"
    image     = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/company-brain-backend:latest"
    essential = true

    portMappings = [{
      containerPort = 8000
      hostPort      = 8000
    }]

    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      { name = "LOG_LEVEL", value = "INFO" },
      { name = "WEAVIATE_URL", value = var.weaviate_url },
      { name = "NEO4J_URI", value = var.neo4j_uri },
      { name = "NEO4J_USER", value = var.neo4j_user },
      { name = "LANGFUSE_PUBLIC_KEY", value = var.langfuse_public_key },
      { name = "LANGFUSE_HOST", value = var.langfuse_host },
      { name = "LLM_PROVIDER", value = "gemini" } # Defaulting to Gemini as resolved
    ]

    secrets = [
      { name = "DATABASE_URL", valueFrom = "${aws_secretsmanager_secret.config.arn}:POSTGRES_DB_URL::" },
      { name = "CELERY_BROKER_URL", valueFrom = "${aws_secretsmanager_secret.config.arn}:REDIS_URL::" },
      { name = "WEAVIATE_API_KEY", valueFrom = "${aws_secretsmanager_secret.config.arn}:WEAVIATE_API_KEY::" },
      { name = "NEO4J_PASSWORD", valueFrom = "${aws_secretsmanager_secret.config.arn}:NEO4J_PASSWORD::" },
      { name = "SKILL_SIGNING_KEY", valueFrom = "${aws_secretsmanager_secret.config.arn}:SKILL_SIGNING_KEY::" },
      { name = "LLM_API_KEY", valueFrom = "${aws_secretsmanager_secret.config.arn}:GEMINI_API_KEY::" },
      { name = "LANGFUSE_SECRET_KEY", valueFrom = "${aws_secretsmanager_secret.config.arn}:LANGFUSE_SECRET_KEY::" }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backend.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "backend"
      }
    }
  }])

  tags = {
    Environment = var.environment
  }
}

# ── Worker Task Definition (Celery) ─────────────────────────────────────────
resource "aws_ecs_task_definition" "worker" {
  family                   = "cb-worker-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "worker"
    image     = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/company-brain-worker:latest"
    essential = true
    command   = ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=info"]

    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      { name = "LOG_LEVEL", value = "INFO" },
      { name = "WEAVIATE_URL", value = var.weaviate_url },
      { name = "NEO4J_URI", value = var.neo4j_uri },
      { name = "NEO4J_USER", value = var.neo4j_user },
      { name = "LANGFUSE_PUBLIC_KEY", value = var.langfuse_public_key },
      { name = "LANGFUSE_HOST", value = var.langfuse_host },
      { name = "LLM_PROVIDER", value = "gemini" }
    ]

    secrets = [
      { name = "DATABASE_URL", valueFrom = "${aws_secretsmanager_secret.config.arn}:POSTGRES_DB_URL::" },
      { name = "CELERY_BROKER_URL", valueFrom = "${aws_secretsmanager_secret.config.arn}:REDIS_URL::" },
      { name = "WEAVIATE_API_KEY", valueFrom = "${aws_secretsmanager_secret.config.arn}:WEAVIATE_API_KEY::" },
      { name = "NEO4J_PASSWORD", valueFrom = "${aws_secretsmanager_secret.config.arn}:NEO4J_PASSWORD::" },
      { name = "SKILL_SIGNING_KEY", valueFrom = "${aws_secretsmanager_secret.config.arn}:SKILL_SIGNING_KEY::" },
      { name = "LLM_API_KEY", valueFrom = "${aws_secretsmanager_secret.config.arn}:GEMINI_API_KEY::" },
      { name = "LANGFUSE_SECRET_KEY", valueFrom = "${aws_secretsmanager_secret.config.arn}:LANGFUSE_SECRET_KEY::" }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])

  tags = {
    Environment = var.environment
  }
}

# ── Backend Service ────────────────────────────────────────────────────────
resource "aws_ecs_service" "backend" {
  name            = "cb-backend-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [aws_subnet.public_1.id, aws_subnet.public_2.id]
    security_groups  = [aws_security_group.backend.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]

  tags = {
    Environment = var.environment
  }
}

# ── Worker Service ─────────────────────────────────────────────────────────
resource "aws_ecs_service" "worker" {
  name            = "cb-worker-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [aws_subnet.public_1.id, aws_subnet.public_2.id]
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = true
  }

  tags = {
    Environment = var.environment
  }
}
