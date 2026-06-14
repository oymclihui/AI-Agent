-- AI-AGENT VastBase 完整脚本（建表 + 基础种子 + 财务处组织）
-- 执行顺序: 本文件一次性执行，或分步执行 init_vastbase_full.sql 再 seed_finance_org_vastbase.sql
-- 数据库名示例: AI-AGENT  schema: public
-- 用法: psql -h <host> -U <user> -d "AI-AGENT" -f init_vastbase_complete.sql
-- AI-AGENT VastBase / PostgreSQL 瀹屾暣鍒濆鍖栬剼鏈?
-- 鐢熸垚: backend/scripts/export_vastbase_init_sql.py
-- 鐩爣 schema: public
--
-- 鐢ㄦ硶 (VastBase / psql):
--   psql -h <host> -p 5432 -U <user> -d <database> -f backend/scripts/sql/init_vastbase_full.sql
--
-- 鍙€夌浜屾锛堣储鍔″缁勭粐鏍戯級:
--   psql ... -f backend/scripts/sql/seed_finance_org_vastbase.sql
--
-- backend/.env 绀轰緥:
--   DB_DRIVER=vastbase
--   DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>:5432/<database>

-- === 1. Schema 鍑嗗 ===
SET search_path TO "public", public;

-- === 2. 鏋氫妇 + 寤鸿〃 + 绱㈠紩 + 澶栭敭锛堝叡 79 鏉¤鍙ワ紝SQLAlchemy create_all 椤哄簭锛?==
CREATE TYPE agentstatus AS ENUM ('active', 'inactive');
CREATE TYPE workflowstatus AS ENUM ('draft', 'active', 'archived');
CREATE TYPE processtype AS ENUM ('sequential', 'hierarchical', 'parallel');
CREATE TYPE executionstatus AS ENUM ('pending', 'awaiting_confirmation', 'running', 'completed', 'failed', 'cancelled');
CREATE TYPE messagerole AS ENUM ('user', 'assistant', 'system', 'tool');
CREATE TYPE kbstatus AS ENUM ('processing', 'ready', 'error');
CREATE TYPE skillstatus AS ENUM ('draft', 'active', 'archived');
CREATE TYPE employeestatus AS ENUM ('active', 'paused', 'archived');
CREATE TYPE scheduletype AS ENUM ('cron', 'interval');
CREATE TYPE employeetasktype AS ENUM ('agent', 'desktop_automation', 'workflow', 'crew');
CREATE TYPE tasktrigger AS ENUM ('schedule', 'manual');
CREATE TYPE desktopdemostatus AS ENUM ('draft', 'ready', 'archived');
CREATE TYPE desktoptaskaction AS ENUM ('capture_start', 'capture_stop', 'replay');

CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	employee_no VARCHAR(64), 
	email VARCHAR(255), 
	password_hash VARCHAR(255) NOT NULL, 
	display_name VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	is_admin BOOLEAN NOT NULL, 
	primary_department_id VARCHAR(36), 
	user_tier VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_users_primary_department_id ON users (primary_department_id);
CREATE UNIQUE INDEX ix_users_employee_no ON users (employee_no);
CREATE INDEX ix_users_user_tier ON users (user_tier);
CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE departments (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	code VARCHAR(64), 
	parent_id VARCHAR(36), 
	path VARCHAR(2048) NOT NULL, 
	level INTEGER NOT NULL, 
	leader_user_id VARCHAR(36), 
	liaison_user_id VARCHAR(36), 
	dept_tier VARCHAR(32) NOT NULL, 
	sort_order INTEGER NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE UNIQUE INDEX ix_departments_code ON departments (code);
CREATE INDEX ix_departments_dept_tier ON departments (dept_tier);
CREATE INDEX ix_departments_path ON departments (path);
CREATE INDEX ix_departments_parent_id ON departments (parent_id);
CREATE INDEX ix_departments_liaison_user_id ON departments (liaison_user_id);
CREATE INDEX ix_departments_leader_user_id ON departments (leader_user_id);

CREATE TABLE model_configs (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	provider VARCHAR(64) NOT NULL, 
	model_id VARCHAR(128) NOT NULL, 
	api_key_encrypted TEXT, 
	base_url VARCHAR(512), 
	config JSON, 
	is_default BOOLEAN, 
	is_active BOOLEAN, 
	context_window INTEGER, 
	cost_per_1k_input FLOAT, 
	cost_per_1k_output FLOAT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
)

;

CREATE TABLE tool_definitions (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description TEXT NOT NULL, 
	category VARCHAR(64) NOT NULL, 
	parameters_schema JSON, 
	implementation_type VARCHAR(32), 
	config JSON, 
	is_active BOOLEAN, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
)

;

CREATE TABLE user_departments (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	department_id VARCHAR(36) NOT NULL, 
	is_primary BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(department_id) REFERENCES departments (id)
)

;
CREATE INDEX ix_user_departments_user_id ON user_departments (user_id);
CREATE INDEX ix_user_departments_department_id ON user_departments (department_id);

CREATE TABLE user_roles (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	role_code VARCHAR(64) NOT NULL, 
	scope_department_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(scope_department_id) REFERENCES departments (id)
)

;
CREATE INDEX ix_user_roles_user_id ON user_roles (user_id);
CREATE INDEX ix_user_roles_scope_department_id ON user_roles (scope_department_id);
CREATE INDEX ix_user_roles_role_code ON user_roles (role_code);

CREATE TABLE permission_audit_logs (
	id VARCHAR(36) NOT NULL, 
	actor_user_id VARCHAR(36) NOT NULL, 
	target_user_id VARCHAR(36) NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	details JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_user_id) REFERENCES users (id), 
	FOREIGN KEY(target_user_id) REFERENCES users (id)
)

;
CREATE INDEX ix_permission_audit_logs_target_user_id ON permission_audit_logs (target_user_id);
CREATE INDEX ix_permission_audit_logs_actor_user_id ON permission_audit_logs (actor_user_id);

CREATE TABLE password_reset_tokens (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	token_hash VARCHAR(128) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	used_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;
CREATE INDEX ix_password_reset_tokens_user_id ON password_reset_tokens (user_id);
CREATE UNIQUE INDEX ix_password_reset_tokens_token_hash ON password_reset_tokens (token_hash);

CREATE TABLE user_mailbox_credentials (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	mailbox_password TEXT NOT NULL, 
	imap_host VARCHAR(255), 
	imap_port INTEGER, 
	imap_use_ssl BOOLEAN NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;
CREATE UNIQUE INDEX ix_user_mailbox_credentials_user_id ON user_mailbox_credentials (user_id);

CREATE TABLE user_kms_credentials (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	kms_user_id VARCHAR(128), 
	api_url VARCHAR(512), 
	api_key TEXT, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;
CREATE UNIQUE INDEX ix_user_kms_credentials_user_id ON user_kms_credentials (user_id);

CREATE TABLE user_model_credentials (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	provider VARCHAR(64) NOT NULL, 
	model_id VARCHAR(128), 
	api_key TEXT NOT NULL, 
	base_url VARCHAR(512), 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;
CREATE INDEX ix_user_model_credentials_user_id ON user_model_credentials (user_id);

CREATE TABLE agents (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36), 
	name VARCHAR(255) NOT NULL, 
	role VARCHAR(255) NOT NULL, 
	goal TEXT NOT NULL, 
	backstory TEXT, 
	status agentstatus NOT NULL, 
	llm_provider VARCHAR(64), 
	llm_model VARCHAR(128), 
	temperature FLOAT, 
	max_iterations INTEGER, 
	tools_config JSON, 
	skills_config JSON, 
	memory_config JSON, 
	metadata JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
)

;
CREATE INDEX ix_agents_owner_id ON agents (owner_id);

CREATE TABLE workflows (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36), 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	status workflowstatus NOT NULL, 
	process_type processtype NOT NULL, 
	graph_definition JSON, 
	agents_config JSON, 
	triggers_config JSON, 
	metadata JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
)

;
CREATE INDEX ix_workflows_owner_id ON workflows (owner_id);

CREATE TABLE knowledge_bases (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36), 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	status kbstatus NOT NULL, 
	embedding_model VARCHAR(128), 
	chunk_size INTEGER, 
	chunk_overlap INTEGER, 
	document_count INTEGER, 
	metadata JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
)

;
CREATE INDEX ix_knowledge_bases_owner_id ON knowledge_bases (owner_id);

CREATE TABLE skills (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36), 
	slug VARCHAR(64) NOT NULL, 
	display_name VARCHAR(255) NOT NULL, 
	description TEXT NOT NULL, 
	instructions_md TEXT NOT NULL, 
	status skillstatus NOT NULL, 
	scope VARCHAR(32) NOT NULL, 
	auto_invoke BOOLEAN NOT NULL, 
	version INTEGER NOT NULL, 
	resources JSON, 
	tools_required JSON, 
	knowledge_base_ids JSON, 
	tags JSON, 
	metadata JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	UNIQUE (slug)
)

;
CREATE INDEX ix_skills_owner_id ON skills (owner_id);

CREATE TABLE desktop_demos (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36), 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	app_name VARCHAR(255), 
	tags JSON, 
	status desktopdemostatus NOT NULL, 
	step_count INTEGER, 
	metadata JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
)

;
CREATE INDEX ix_desktop_demos_owner_id ON desktop_demos (owner_id);

CREATE TABLE desktop_sidecars (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36) NOT NULL, 
	device_id VARCHAR(128) NOT NULL, 
	device_name VARCHAR(255) NOT NULL, 
	hostname VARCHAR(255), 
	platform VARCHAR(64), 
	last_seen_at TIMESTAMP WITH TIME ZONE, 
	metadata JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
)

;
CREATE INDEX ix_desktop_sidecars_device_id ON desktop_sidecars (device_id);
CREATE INDEX ix_desktop_sidecars_owner_id ON desktop_sidecars (owner_id);

CREATE TABLE harness_pending_actions (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36) NOT NULL, 
	tool_name VARCHAR(128) NOT NULL, 
	tool_args JSON, 
	risk_level VARCHAR(16) NOT NULL, 
	status executionstatus NOT NULL, 
	source VARCHAR(64), 
	source_id VARCHAR(36), 
	result TEXT, 
	error_message TEXT, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
)

;
CREATE INDEX ix_harness_pending_actions_owner_id ON harness_pending_actions (owner_id);

CREATE TABLE workflow_executions (
	id VARCHAR(36) NOT NULL, 
	workflow_id VARCHAR(36) NOT NULL, 
	status executionstatus NOT NULL, 
	input_data JSON, 
	output_data JSON, 
	error_message TEXT, 
	state_snapshot JSON, 
	token_usage JSON, 
	duration_ms INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workflow_id) REFERENCES workflows (id)
)

;

CREATE TABLE conversations (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36), 
	title VARCHAR(255), 
	agent_id VARCHAR(36), 
	workflow_id VARCHAR(36), 
	knowledge_base_ids JSON, 
	skills_config JSON, 
	memory_type VARCHAR(64), 
	is_active BOOLEAN, 
	metadata JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	FOREIGN KEY(agent_id) REFERENCES agents (id), 
	FOREIGN KEY(workflow_id) REFERENCES workflows (id)
)

;
CREATE INDEX ix_conversations_owner_id ON conversations (owner_id);

CREATE TABLE documents (
	id VARCHAR(36) NOT NULL, 
	knowledge_base_id VARCHAR(36) NOT NULL, 
	filename VARCHAR(512) NOT NULL, 
	file_type VARCHAR(32) NOT NULL, 
	file_size INTEGER, 
	storage_path VARCHAR(1024), 
	status kbstatus NOT NULL, 
	chunk_count INTEGER, 
	metadata JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id)
)

;

CREATE TABLE digital_employees (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36), 
	department_id VARCHAR(36), 
	parent_employee_id VARCHAR(36), 
	sort_order INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	title VARCHAR(255), 
	description TEXT, 
	status employeestatus NOT NULL, 
	agent_id VARCHAR(36) NOT NULL, 
	skills_config JSON, 
	knowledge_base_ids JSON, 
	timezone VARCHAR(64) NOT NULL, 
	metadata JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	FOREIGN KEY(department_id) REFERENCES departments (id), 
	FOREIGN KEY(parent_employee_id) REFERENCES digital_employees (id), 
	FOREIGN KEY(agent_id) REFERENCES agents (id)
)

;
CREATE INDEX ix_digital_employees_department_id ON digital_employees (department_id);
CREATE INDEX ix_digital_employees_parent_employee_id ON digital_employees (parent_employee_id);
CREATE INDEX ix_digital_employees_owner_id ON digital_employees (owner_id);

CREATE TABLE desktop_tasks (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36) NOT NULL, 
	demo_id VARCHAR(36), 
	sidecar_id VARCHAR(36), 
	action desktoptaskaction NOT NULL, 
	status executionstatus NOT NULL, 
	instructions TEXT, 
	input_data JSON, 
	output_data JSON, 
	error_message TEXT, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	FOREIGN KEY(demo_id) REFERENCES desktop_demos (id), 
	FOREIGN KEY(sidecar_id) REFERENCES desktop_sidecars (id)
)

;
CREATE INDEX ix_desktop_tasks_owner_id ON desktop_tasks (owner_id);

CREATE TABLE agent_executions (
	id VARCHAR(36) NOT NULL, 
	workflow_execution_id VARCHAR(36), 
	agent_id VARCHAR(36) NOT NULL, 
	task_description TEXT NOT NULL, 
	status executionstatus NOT NULL, 
	output TEXT, 
	error_message TEXT, 
	token_usage JSON, 
	steps JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workflow_execution_id) REFERENCES workflow_executions (id), 
	FOREIGN KEY(agent_id) REFERENCES agents (id)
)

;

CREATE TABLE messages (
	id VARCHAR(36) NOT NULL, 
	conversation_id VARCHAR(36) NOT NULL, 
	role messagerole NOT NULL, 
	content TEXT NOT NULL, 
	tool_calls JSON, 
	token_usage JSON, 
	metadata JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id)
)

;

CREATE TABLE employee_scheduled_tasks (
	id VARCHAR(36) NOT NULL, 
	employee_id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	enabled BOOLEAN NOT NULL, 
	schedule_type scheduletype NOT NULL, 
	cron_expression VARCHAR(128), 
	interval_seconds INTEGER, 
	timezone VARCHAR(64) NOT NULL, 
	task_type employeetasktype NOT NULL, 
	task_config JSON, 
	retry_max INTEGER, 
	timeout_seconds INTEGER, 
	last_run_at TIMESTAMP WITH TIME ZONE, 
	next_run_at TIMESTAMP WITH TIME ZONE, 
	last_status VARCHAR(32), 
	metadata JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(employee_id) REFERENCES digital_employees (id)
)

;

CREATE TABLE employee_task_runs (
	id VARCHAR(36) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	employee_id VARCHAR(36) NOT NULL, 
	status executionstatus NOT NULL, 
	triggered_by tasktrigger NOT NULL, 
	input_data JSON, 
	output_data JSON, 
	error_message TEXT, 
	token_usage JSON, 
	duration_ms INTEGER, 
	agent_execution_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES employee_scheduled_tasks (id), 
	FOREIGN KEY(employee_id) REFERENCES digital_employees (id), 
	FOREIGN KEY(agent_execution_id) REFERENCES agent_executions (id)
)

;
ALTER TABLE departments ADD FOREIGN KEY(leader_user_id) REFERENCES users (id);
ALTER TABLE users ADD FOREIGN KEY(primary_department_id) REFERENCES departments (id);
ALTER TABLE departments ADD FOREIGN KEY(liaison_user_id) REFERENCES users (id);
ALTER TABLE departments ADD FOREIGN KEY(parent_id) REFERENCES departments (id);

-- === 3. 缁撴瀯琛ヤ竵锛堝箓绛夛紝鏃у簱鍗囩骇鏃跺彲鍗曠嫭鎵ц锛?==
-- agents.skills_config锛堢己鍒楁椂锛?
ALTER TABLE agents ADD COLUMN IF NOT EXISTS skills_config JSONB NOT NULL DEFAULT '[]'::jsonb;
-- conversations.skills_config锛堢己鍒楁椂锛?
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS skills_config JSONB NOT NULL DEFAULT '[]'::jsonb;
-- users / digital_employees 缁勭粐瀛楁锛堢己鍒楁椂锛屾寜瀹為檯妫€娴嬬粨鏋滆拷鍔?ALTER锛?
-- executionstatus / employeetasktype 鏋氫妇鏂板€硷紙缂哄€兼椂锛?
ALTER TYPE executionstatus ADD VALUE IF NOT EXISTS 'awaiting_confirmation';
ALTER TYPE employeetasktype ADD VALUE IF NOT EXISTS 'workflow';
ALTER TYPE employeetasktype ADD VALUE IF NOT EXISTS 'crew';

-- === 5. 骞冲彴鏈€灏忕瀛愶紙绠＄悊鍛?+ 鏍归儴闂紝骞傜瓑锛?==
-- 榛樿璐﹀彿: admin / admin123 锛堥娆＄櫥褰曞悗璇蜂慨鏀瑰瘑鐮侊級
-- 瀹屾暣妯℃澘鏁版嵁锛堟櫤鑳戒綋銆佸伐浣滄祦銆丮odel Hub 绛夛級璇风敤 Web銆岃缃?鈫?鏁版嵁搴撳垵濮嬪寲銆嶆垨:
--   cd backend && python scripts/init_database.py

DO $$
DECLARE
  root_id VARCHAR(36) := '00000000-0000-4000-8000-000000000001';
  admin_id VARCHAR(36) := '00000000-0000-4000-8000-000000000002';
  role_id VARCHAR(36) := '00000000-0000-4000-8000-000000000003';
  memb_id VARCHAR(36) := '00000000-0000-4000-8000-000000000004';
  pwd_hash VARCHAR(255) := '$2b$12$wI.alQMnnI/aoahBlSd3ru0QiiIBYvWIl35v7k2zwBvjFu9mG33cC';
  ts TIMESTAMPTZ := NOW();
BEGIN
  IF NOT EXISTS (SELECT 1 FROM departments WHERE code = 'root') THEN
    INSERT INTO departments (
      id, name, code, parent_id, path, level, sort_order, dept_tier, is_active, created_at, updated_at
    ) VALUES (
      root_id, '鍏ㄥ叕鍙?, 'root', NULL,
      '/' || root_id || '/', 0, 0, 'business', TRUE, ts, ts
    );
  END IF;

  IF NOT EXISTS (SELECT 1 FROM users WHERE employee_no = 'admin') THEN
    INSERT INTO users (
      id, employee_no, email, password_hash, display_name,
      is_active, is_admin, primary_department_id, user_tier, created_at, updated_at
    ) VALUES (
      admin_id, 'admin', 'admin@local', pwd_hash, 'Administrator',
      TRUE, TRUE, root_id, 'staff', ts, ts
    );
  END IF;

  UPDATE users SET is_admin = TRUE, primary_department_id = root_id
  WHERE employee_no = 'admin';

  IF NOT EXISTS (
    SELECT 1 FROM user_roles ur
    JOIN users u ON u.id = ur.user_id
    WHERE u.employee_no = 'admin' AND ur.role_code = 'super_admin'
  ) THEN
    INSERT INTO user_roles (id, user_id, role_code, scope_department_id, created_at, updated_at)
    SELECT role_id, u.id, 'super_admin', NULL, ts, ts
    FROM users u
    WHERE u.employee_no = 'admin';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM user_departments ud
    JOIN users u ON u.id = ud.user_id
    WHERE u.employee_no = 'admin' AND ud.is_primary = TRUE
  ) THEN
    INSERT INTO user_departments (id, user_id, department_id, is_primary, created_at, updated_at)
    SELECT memb_id, u.id, root_id, TRUE, ts, ts
    FROM users u
    WHERE u.employee_no = 'admin';
  END IF;
END $$;

-- === 瀹屾垚 ===
-- 鐧诲綍: admin / admin123
-- 妯℃澘鏅鸿兘浣撱€佸伐浣滄祦銆丮odel Hub 绛夎杩愯 Python 鍒濆鍖栨垨 Web 璁剧疆鍚戝銆?


-- =============================================================================
-- 财务处组织种子（可选，需先有 root 部门）
-- =============================================================================

-- Finance org seed for PostgreSQL / VastBase (idempotent).
--
-- Prerequisites:
--   1. Platform tables exist (run backend init / migrate first).
--   2. Root department (code = 'root', 鍏ㄥ叕鍙? exists from seed_org_rbac.
--
-- Usage (VastBase / psql):
--   psql -h <host> -U <user> -d <database> -f backend/scripts/sql/seed_finance_org_vastbase.sql
--
-- Default password for all seeded users: ChangeMe@2026
-- Employee numbers are numeric placeholders 鈥?edit display_name / employee_no in admin UI later.

DO $$
DECLARE
  root_id VARCHAR(36);
  l1_id VARCHAR(36) := 'a1111111-1111-4111-8111-111111111101';
  l2_id VARCHAR(36) := 'a1111111-1111-4111-8111-111111111102';
  l3_jr VARCHAR(36) := 'a1111111-1111-4111-8111-111111111103';
  l3_ops VARCHAR(36) := 'a1111111-1111-4111-8111-111111111104';
  l3_reg VARCHAR(36) := 'a1111111-1111-4111-8111-111111111105';
  l3_fin VARCHAR(36) := 'a1111111-1111-4111-8111-111111111106';
  l3_tax VARCHAR(36) := 'a1111111-1111-4111-8111-111111111107';
  l3_eu VARCHAR(36) := 'a1111111-1111-4111-8111-111111111108';
  pwd_hash VARCHAR(255) := '$2b$12$3fLZVhu2FDwFFMVCdnxvIeQEtky4m7HNU3w7CvuiqaHJNCa7S0Sfy';
  ts TIMESTAMPTZ := NOW();
BEGIN
  SELECT id INTO root_id FROM departments WHERE code = 'root' LIMIT 1;
  IF root_id IS NULL THEN
    RAISE EXCEPTION 'Root department (code=root) not found 鈥?run platform init first';
  END IF;

  -- 鈹€鈹€ Departments 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
  INSERT INTO departments (
    id, name, code, parent_id, path, level, sort_order, dept_tier, is_active, created_at, updated_at
  ) VALUES
    (l1_id, '璐㈠姟澶?, 'fin-dept-l1', root_id,
     '/' || root_id || '/' || l1_id || '/', 1, 1, 'business', TRUE, ts, ts),
    (l2_id, '璐㈠姟鏀寔涓績', 'fin-support-center', l1_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/', 2, 1, 'business', TRUE, ts, ts),
    (l3_jr, '閲戣瀺璐㈠姟閮?, 'fin-jr-dept', l2_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/' || l3_jr || '/', 3, 1, 'business', TRUE, ts, ts),
    (l3_ops, '娴峰缁忚惀绠＄悊閮?, 'fin-overseas-ops', l2_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/' || l3_ops || '/', 3, 2, 'business', TRUE, ts, ts),
    (l3_reg, '鍖哄煙璐㈢粡绠＄悊閮?, 'fin-regional', l2_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/' || l3_reg || '/', 3, 3, 'business', TRUE, ts, ts),
    (l3_fin, '娴峰璐㈠姟绠＄悊閮?, 'fin-overseas-finance', l2_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/' || l3_fin || '/', 3, 4, 'business', TRUE, ts, ts),
    (l3_tax, '娴峰绋庡姟绠＄悊閮?, 'fin-overseas-tax', l2_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/' || l3_tax || '/', 3, 5, 'business', TRUE, ts, ts),
    (l3_eu, '娆ф床璐㈠姟閮?, 'fin-europe', l2_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/' || l3_eu || '/', 3, 6, 'business', TRUE, ts, ts)
  ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    parent_id = EXCLUDED.parent_id,
    path = EXCLUDED.path,
    level = EXCLUDED.level,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    updated_at = ts;

  -- 鈹€鈹€ Users 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
  INSERT INTO users (
    id, employee_no, email, password_hash, display_name,
    is_active, is_admin, primary_department_id, user_tier, created_at, updated_at
  ) VALUES
    -- 璐㈠姟鏀寔涓績
    ('b1000001-0001-4001-8001-000000000001', '100001', NULL, pwd_hash, '闄堢懚', TRUE, FALSE, l2_id, 'staff', ts, ts),
    ('b1000002-0002-4002-8002-000000000002', '100002', NULL, pwd_hash, '鍒樺僵绾?, TRUE, FALSE, l2_id, 'staff', ts, ts),
    ('b1000003-0003-4003-8003-000000000003', '100003', NULL, pwd_hash, '浣欓泤濡?, TRUE, FALSE, l2_id, 'staff', ts, ts),
    -- 閲戣瀺璐㈠姟閮?    ('c1100001-0001-4001-8001-010000000001', '110001', NULL, pwd_hash, '110001', TRUE, FALSE, l3_jr, 'staff', ts, ts),
    ('c1100002-0002-4002-8002-010000000002', '110002', NULL, pwd_hash, '110002', TRUE, FALSE, l3_jr, 'staff', ts, ts),
    ('c1100003-0003-4003-8003-010000000003', '110003', NULL, pwd_hash, '110003', TRUE, FALSE, l3_jr, 'staff', ts, ts),
    -- 娴峰缁忚惀绠＄悊閮?    ('c1200001-0001-4001-8001-020000000001', '120001', NULL, pwd_hash, '120001', TRUE, FALSE, l3_ops, 'staff', ts, ts),
    ('c1200002-0002-4002-8002-020000000002', '120002', NULL, pwd_hash, '120002', TRUE, FALSE, l3_ops, 'staff', ts, ts),
    ('c1200003-0003-4003-8003-020000000003', '120003', NULL, pwd_hash, '120003', TRUE, FALSE, l3_ops, 'staff', ts, ts),
    -- 鍖哄煙璐㈢粡绠＄悊閮?    ('c1300001-0001-4001-8001-030000000001', '130001', NULL, pwd_hash, '130001', TRUE, FALSE, l3_reg, 'staff', ts, ts),
    ('c1300002-0002-4002-8002-030000000002', '130002', NULL, pwd_hash, '130002', TRUE, FALSE, l3_reg, 'staff', ts, ts),
    ('c1300003-0003-4003-8003-030000000003', '130003', NULL, pwd_hash, '130003', TRUE, FALSE, l3_reg, 'staff', ts, ts),
    -- 娴峰璐㈠姟绠＄悊閮?    ('c1400001-0001-4001-8001-040000000001', '140001', NULL, pwd_hash, '140001', TRUE, FALSE, l3_fin, 'staff', ts, ts),
    ('c1400002-0002-4002-8002-040000000002', '140002', NULL, pwd_hash, '140002', TRUE, FALSE, l3_fin, 'staff', ts, ts),
    ('c1400003-0003-4003-8003-040000000003', '140003', NULL, pwd_hash, '140003', TRUE, FALSE, l3_fin, 'staff', ts, ts),
    -- 娴峰绋庡姟绠＄悊閮?    ('c1500001-0001-4001-8001-050000000001', '150001', NULL, pwd_hash, '150001', TRUE, FALSE, l3_tax, 'staff', ts, ts),
    ('c1500002-0002-4002-8002-050000000002', '150002', NULL, pwd_hash, '150002', TRUE, FALSE, l3_tax, 'staff', ts, ts),
    ('c1500003-0003-4003-8003-050000000003', '150003', NULL, pwd_hash, '150003', TRUE, FALSE, l3_tax, 'staff', ts, ts),
    -- 娆ф床璐㈠姟閮?    ('c1600001-0001-4001-8001-060000000001', '160001', NULL, pwd_hash, '160001', TRUE, FALSE, l3_eu, 'staff', ts, ts),
    ('c1600002-0002-4002-8002-060000000002', '160002', NULL, pwd_hash, '160002', TRUE, FALSE, l3_eu, 'staff', ts, ts),
    ('c1600003-0003-4003-8003-060000000003', '160003', NULL, pwd_hash, '160003', TRUE, FALSE, l3_eu, 'staff', ts, ts)
  ON CONFLICT (employee_no) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    password_hash = EXCLUDED.password_hash,
    primary_department_id = EXCLUDED.primary_department_id,
    is_active = TRUE,
    updated_at = ts;

  -- 鈹€鈹€ Department memberships (fixed ids for VastBase compatibility) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
  INSERT INTO user_departments (id, user_id, department_id, is_primary, created_at, updated_at)
  VALUES
    ('d1000001-0001-4001-8001-000000000001', 'b1000001-0001-4001-8001-000000000001', l2_id, TRUE, ts, ts),
    ('d1000002-0002-4002-8002-000000000002', 'b1000002-0002-4002-8002-000000000002', l2_id, TRUE, ts, ts),
    ('d1000003-0003-4003-8003-000000000003', 'b1000003-0003-4003-8003-000000000003', l2_id, TRUE, ts, ts),
    ('d1100001-0001-4001-8001-010000000001', 'c1100001-0001-4001-8001-010000000001', l3_jr, TRUE, ts, ts),
    ('d1100002-0002-4002-8002-010000000002', 'c1100002-0002-4002-8002-010000000002', l3_jr, TRUE, ts, ts),
    ('d1100003-0003-4003-8003-010000000003', 'c1100003-0003-4003-8003-010000000003', l3_jr, TRUE, ts, ts),
    ('d1200001-0001-4001-8001-020000000001', 'c1200001-0001-4001-8001-020000000001', l3_ops, TRUE, ts, ts),
    ('d1200002-0002-4002-8002-020000000002', 'c1200002-0002-4002-8002-020000000002', l3_ops, TRUE, ts, ts),
    ('d1200003-0003-4003-8003-020000000003', 'c1200003-0003-4003-8003-020000000003', l3_ops, TRUE, ts, ts),
    ('d1300001-0001-4001-8001-030000000001', 'c1300001-0001-4001-8001-030000000001', l3_reg, TRUE, ts, ts),
    ('d1300002-0002-4002-8002-030000000002', 'c1300002-0002-4002-8002-030000000002', l3_reg, TRUE, ts, ts),
    ('d1300003-0003-4003-8003-030000000003', 'c1300003-0003-4003-8003-030000000003', l3_reg, TRUE, ts, ts),
    ('d1400001-0001-4001-8001-040000000001', 'c1400001-0001-4001-8001-040000000001', l3_fin, TRUE, ts, ts),
    ('d1400002-0002-4002-8002-040000000002', 'c1400002-0002-4002-8002-040000000002', l3_fin, TRUE, ts, ts),
    ('d1400003-0003-4003-8003-040000000003', 'c1400003-0003-4003-8003-040000000003', l3_fin, TRUE, ts, ts),
    ('d1500001-0001-4001-8001-050000000001', 'c1500001-0001-4001-8001-050000000001', l3_tax, TRUE, ts, ts),
    ('d1500002-0002-4002-8002-050000000002', 'c1500002-0002-4002-8002-050000000002', l3_tax, TRUE, ts, ts),
    ('d1500003-0003-4003-8003-050000000003', 'c1500003-0003-4003-8003-050000000003', l3_tax, TRUE, ts, ts),
    ('d1600001-0001-4001-8001-060000000001', 'c1600001-0001-4001-8001-060000000001', l3_eu, TRUE, ts, ts),
    ('d1600002-0002-4002-8002-060000000002', 'c1600002-0002-4002-8002-060000000002', l3_eu, TRUE, ts, ts),
    ('d1600003-0003-4003-8003-060000000003', 'c1600003-0003-4003-8003-060000000003', l3_eu, TRUE, ts, ts)
  ON CONFLICT (id) DO UPDATE SET
    department_id = EXCLUDED.department_id,
    is_primary = TRUE,
    updated_at = ts;

  -- 鈹€鈹€ Roles 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
  INSERT INTO user_roles (id, user_id, role_code, scope_department_id, created_at, updated_at)
  VALUES
    ('r1000001-0001-4001-8001-000000000001', 'b1000001-0001-4001-8001-000000000001', 'dept_leader', l2_id, ts, ts),
    ('r1100001-0001-4001-8001-010000000001', 'c1100001-0001-4001-8001-010000000001', 'dept_leader', l3_jr, ts, ts),
    ('r1200001-0001-4001-8001-020000000001', 'c1200001-0001-4001-8001-020000000001', 'dept_leader', l3_ops, ts, ts),
    ('r1300001-0001-4001-8001-030000000001', 'c1300001-0001-4001-8001-030000000001', 'dept_leader', l3_reg, ts, ts),
    ('r1400001-0001-4001-8001-040000000001', 'c1400001-0001-4001-8001-040000000001', 'dept_leader', l3_fin, ts, ts),
    ('r1500001-0001-4001-8001-050000000001', 'c1500001-0001-4001-8001-050000000001', 'dept_leader', l3_tax, ts, ts),
    ('r1600001-0001-4001-8001-060000000001', 'c1600001-0001-4001-8001-060000000001', 'dept_leader', l3_eu, ts, ts),
    ('r1000002-0002-4002-8002-000000000002', 'b1000002-0002-4002-8002-000000000002', 'operator', l2_id, ts, ts),
    ('r1000003-0003-4003-8003-000000000003', 'b1000003-0003-4003-8003-000000000003', 'operator', l2_id, ts, ts),
    ('r1100002-0002-4002-8002-010000000002', 'c1100002-0002-4002-8002-010000000002', 'operator', l3_jr, ts, ts),
    ('r1100003-0003-4003-8003-010000000003', 'c1100003-0003-4003-8003-010000000003', 'operator', l3_jr, ts, ts),
    ('r1200002-0002-4002-8002-020000000002', 'c1200002-0002-4002-8002-020000000002', 'operator', l3_ops, ts, ts),
    ('r1200003-0003-4003-8003-020000000003', 'c1200003-0003-4003-8003-020000000003', 'operator', l3_ops, ts, ts),
    ('r1300002-0002-4002-8002-030000000002', 'c1300002-0002-4002-8002-030000000002', 'operator', l3_reg, ts, ts),
    ('r1300003-0003-4003-8003-030000000003', 'c1300003-0003-4003-8003-030000000003', 'operator', l3_reg, ts, ts),
    ('r1400002-0002-4002-8002-040000000002', 'c1400002-0002-4002-8002-040000000002', 'operator', l3_fin, ts, ts),
    ('r1400003-0003-4003-8003-040000000003', 'c1400003-0003-4003-8003-040000000003', 'operator', l3_fin, ts, ts),
    ('r1500002-0002-4002-8002-050000000002', 'c1500002-0002-4002-8002-050000000002', 'operator', l3_tax, ts, ts),
    ('r1500003-0003-4003-8003-050000000003', 'c1500003-0003-4003-8003-050000000003', 'operator', l3_tax, ts, ts),
    ('r1600002-0002-4002-8002-060000000002', 'c1600002-0002-4002-8002-060000000002', 'operator', l3_eu, ts, ts),
    ('r1600003-0003-4003-8003-060000000003', 'c1600003-0003-4003-8003-060000000003', 'operator', l3_eu, ts, ts)
  ON CONFLICT (id) DO UPDATE SET
    role_code = EXCLUDED.role_code,
    scope_department_id = EXCLUDED.scope_department_id,
    updated_at = ts;

  -- 鈹€鈹€ Department leaders 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
  UPDATE departments SET leader_user_id = 'b1000001-0001-4001-8001-000000000001', updated_at = ts
  WHERE code = 'fin-support-center';

  UPDATE departments SET leader_user_id = u.id, updated_at = ts
  FROM users u
  WHERE departments.code = 'fin-jr-dept' AND u.employee_no = '110001';
  UPDATE departments SET leader_user_id = u.id, updated_at = ts
  FROM users u
  WHERE departments.code = 'fin-overseas-ops' AND u.employee_no = '120001';
  UPDATE departments SET leader_user_id = u.id, updated_at = ts
  FROM users u
  WHERE departments.code = 'fin-regional' AND u.employee_no = '130001';
  UPDATE departments SET leader_user_id = u.id, updated_at = ts
  FROM users u
  WHERE departments.code = 'fin-overseas-finance' AND u.employee_no = '140001';
  UPDATE departments SET leader_user_id = u.id, updated_at = ts
  FROM users u
  WHERE departments.code = 'fin-overseas-tax' AND u.employee_no = '150001';
  UPDATE departments SET leader_user_id = u.id, updated_at = ts
  FROM users u
  WHERE departments.code = 'fin-europe' AND u.employee_no = '160001';

  RAISE NOTICE 'Finance org seed completed (8 departments, 21 users). Default password: ChangeMe@2026';
END $$;

