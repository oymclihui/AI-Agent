-- Finance org seed for PostgreSQL / VastBase (idempotent).
--
-- Prerequisites:
--   1. Platform tables exist (run backend init / migrate first).
--   2. Root department (code = 'root', 全公司) exists from seed_org_rbac.
--
-- Usage (VastBase / psql):
--   psql -h <host> -U <user> -d <database> -f backend/scripts/sql/seed_finance_org_vastbase.sql
--
-- Default password for all seeded users: ChangeMe@2026
-- Employee numbers are numeric placeholders — edit display_name / employee_no in admin UI later.

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
    RAISE EXCEPTION 'Root department (code=root) not found — run platform init first';
  END IF;

  -- ── Departments ──────────────────────────────────────────────────────────
  INSERT INTO departments (
    id, name, code, parent_id, path, level, sort_order, dept_tier, is_active, created_at, updated_at
  ) VALUES
    (l1_id, '财务处', 'fin-dept-l1', root_id,
     '/' || root_id || '/' || l1_id || '/', 1, 1, 'business', TRUE, ts, ts),
    (l2_id, '财务支持中心', 'fin-support-center', l1_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/', 2, 1, 'business', TRUE, ts, ts),
    (l3_jr, '金融财务部', 'fin-jr-dept', l2_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/' || l3_jr || '/', 3, 1, 'business', TRUE, ts, ts),
    (l3_ops, '海外经营管理部', 'fin-overseas-ops', l2_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/' || l3_ops || '/', 3, 2, 'business', TRUE, ts, ts),
    (l3_reg, '区域财经管理部', 'fin-regional', l2_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/' || l3_reg || '/', 3, 3, 'business', TRUE, ts, ts),
    (l3_fin, '海外财务管理部', 'fin-overseas-finance', l2_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/' || l3_fin || '/', 3, 4, 'business', TRUE, ts, ts),
    (l3_tax, '海外税务管理部', 'fin-overseas-tax', l2_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/' || l3_tax || '/', 3, 5, 'business', TRUE, ts, ts),
    (l3_eu, '欧洲财务部', 'fin-europe', l2_id,
     '/' || root_id || '/' || l1_id || '/' || l2_id || '/' || l3_eu || '/', 3, 6, 'business', TRUE, ts, ts)
  ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    parent_id = EXCLUDED.parent_id,
    path = EXCLUDED.path,
    level = EXCLUDED.level,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    updated_at = ts;

  -- ── Users ────────────────────────────────────────────────────────────────
  INSERT INTO users (
    id, employee_no, email, password_hash, display_name,
    is_active, is_admin, primary_department_id, user_tier, created_at, updated_at
  ) VALUES
    -- 财务支持中心
    ('b1000001-0001-4001-8001-000000000001', '100001', NULL, pwd_hash, '陈瑶', TRUE, FALSE, l2_id, 'staff', ts, ts),
    ('b1000002-0002-4002-8002-000000000002', '100002', NULL, pwd_hash, '刘彩红', TRUE, FALSE, l2_id, 'staff', ts, ts),
    ('b1000003-0003-4003-8003-000000000003', '100003', NULL, pwd_hash, '余雅妮', TRUE, FALSE, l2_id, 'staff', ts, ts),
    -- 金融财务部
    ('c1100001-0001-4001-8001-010000000001', '110001', NULL, pwd_hash, '110001', TRUE, FALSE, l3_jr, 'staff', ts, ts),
    ('c1100002-0002-4002-8002-010000000002', '110002', NULL, pwd_hash, '110002', TRUE, FALSE, l3_jr, 'staff', ts, ts),
    ('c1100003-0003-4003-8003-010000000003', '110003', NULL, pwd_hash, '110003', TRUE, FALSE, l3_jr, 'staff', ts, ts),
    -- 海外经营管理部
    ('c1200001-0001-4001-8001-020000000001', '120001', NULL, pwd_hash, '120001', TRUE, FALSE, l3_ops, 'staff', ts, ts),
    ('c1200002-0002-4002-8002-020000000002', '120002', NULL, pwd_hash, '120002', TRUE, FALSE, l3_ops, 'staff', ts, ts),
    ('c1200003-0003-4003-8003-020000000003', '120003', NULL, pwd_hash, '120003', TRUE, FALSE, l3_ops, 'staff', ts, ts),
    -- 区域财经管理部
    ('c1300001-0001-4001-8001-030000000001', '130001', NULL, pwd_hash, '130001', TRUE, FALSE, l3_reg, 'staff', ts, ts),
    ('c1300002-0002-4002-8002-030000000002', '130002', NULL, pwd_hash, '130002', TRUE, FALSE, l3_reg, 'staff', ts, ts),
    ('c1300003-0003-4003-8003-030000000003', '130003', NULL, pwd_hash, '130003', TRUE, FALSE, l3_reg, 'staff', ts, ts),
    -- 海外财务管理部
    ('c1400001-0001-4001-8001-040000000001', '140001', NULL, pwd_hash, '140001', TRUE, FALSE, l3_fin, 'staff', ts, ts),
    ('c1400002-0002-4002-8002-040000000002', '140002', NULL, pwd_hash, '140002', TRUE, FALSE, l3_fin, 'staff', ts, ts),
    ('c1400003-0003-4003-8003-040000000003', '140003', NULL, pwd_hash, '140003', TRUE, FALSE, l3_fin, 'staff', ts, ts),
    -- 海外税务管理部
    ('c1500001-0001-4001-8001-050000000001', '150001', NULL, pwd_hash, '150001', TRUE, FALSE, l3_tax, 'staff', ts, ts),
    ('c1500002-0002-4002-8002-050000000002', '150002', NULL, pwd_hash, '150002', TRUE, FALSE, l3_tax, 'staff', ts, ts),
    ('c1500003-0003-4003-8003-050000000003', '150003', NULL, pwd_hash, '150003', TRUE, FALSE, l3_tax, 'staff', ts, ts),
    -- 欧洲财务部
    ('c1600001-0001-4001-8001-060000000001', '160001', NULL, pwd_hash, '160001', TRUE, FALSE, l3_eu, 'staff', ts, ts),
    ('c1600002-0002-4002-8002-060000000002', '160002', NULL, pwd_hash, '160002', TRUE, FALSE, l3_eu, 'staff', ts, ts),
    ('c1600003-0003-4003-8003-060000000003', '160003', NULL, pwd_hash, '160003', TRUE, FALSE, l3_eu, 'staff', ts, ts)
  ON CONFLICT (employee_no) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    password_hash = EXCLUDED.password_hash,
    primary_department_id = EXCLUDED.primary_department_id,
    is_active = TRUE,
    updated_at = ts;

  -- ── Department memberships (fixed ids for VastBase compatibility) ─────────
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

  -- ── Roles ──────────────────────────────────────────────────────────────
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

  -- ── Department leaders ───────────────────────────────────────────────────
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
