resource "aws_secretsmanager_secret" "config" {
  name                    = "company-brain-secrets-${var.environment}"
  description             = "App credentials for Company Brain ${var.environment}"
  recovery_window_in_days = 0 # Forces deletion upon destroy for staging/development convenience
}

resource "aws_secretsmanager_secret_version" "config" {
  secret_id = aws_secretsmanager_secret.config.id
  secret_string = jsonencode({
    POSTGRES_DB_URL     = var.postgres_db_url
    REDIS_URL           = var.redis_url
    WEAVIATE_API_KEY    = var.weaviate_api_key
    NEO4J_PASSWORD      = var.neo4j_password
    SKILL_SIGNING_KEY   = var.skill_signing_key
    OPENAI_API_KEY      = var.openai_api_key
    GEMINI_API_KEY      = var.gemini_api_key
    ANTHROPIC_API_KEY   = var.anthropic_api_key
    LANGFUSE_SECRET_KEY = var.langfuse_secret_key
  })
}
