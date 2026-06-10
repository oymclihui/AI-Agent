-- Run on 192.168.50.10 as PostgreSQL superuser:
--   psql -U postgres -f init_ai_agent.sql
-- Creates database/user "AI-AGENT" (quoted because of hyphen).

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'AI-AGENT') THEN
    CREATE ROLE "AI-AGENT" WITH LOGIN PASSWORD 'AI-AGENT';
  ELSE
    ALTER ROLE "AI-AGENT" WITH LOGIN PASSWORD 'AI-AGENT';
  END IF;
END
$$;

SELECT 'CREATE DATABASE "AI-AGENT" OWNER "AI-AGENT" ENCODING UTF8'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'AI-AGENT')\gexec

GRANT ALL PRIVILEGES ON DATABASE "AI-AGENT" TO "AI-AGENT";
