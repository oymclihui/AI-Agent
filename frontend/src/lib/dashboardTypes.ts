export interface DashboardOverview {
  generated_at: string;
  timezone: string;
  day_start: string;
  scheduler: {
    running: boolean;
    last_tick: string | null;
    last_error: string | null;
    interval_seconds: number;
  };
  health: { status: string };
  platform: {
    employees: number;
    agents: number;
    skills: number;
    workflows: number;
    knowledge_bases: number;
    active_employees: number;
    enabled_tasks: number;
  };
  today: {
    total_runs: number;
    completed: number;
    failed: number;
    running: number;
    active_employees: number;
    avg_duration_ms: number | null;
    token_usage: { total_tokens?: number; prompt_tokens?: number; completion_tokens?: number };
  };
  hourly_runs: { hour: number; count: number; completed: number; failed: number }[];
  employees: DashboardEmployeeCard[];
  recent_runs: DashboardRecentRun[];
}

export interface DashboardEmployeeCard {
  id: string;
  name: string;
  title: string | null;
  agent_name: string | null;
  employee_status: string;
  operational_status: string;
  task_count: number;
  enabled_tasks: number;
  next_run_at: string | null;
  today_runs: number;
  today_success: number;
  today_failed: number;
  last_run: {
    id: string;
    status: string;
    at: string;
    task_name: string | null;
    task_id: string | null;
    summary: string | null;
    triggered_by: string | null;
    duration_ms: number | null;
  } | null;
}

export interface DashboardRecentRun {
  id: string;
  employee_id: string;
  employee_name: string;
  task_id: string;
  task_name: string | null;
  status: string;
  triggered_by: string;
  created_at: string;
  duration_ms: number | null;
  prompt_summary: string | null;
  output_summary: string | null;
}
