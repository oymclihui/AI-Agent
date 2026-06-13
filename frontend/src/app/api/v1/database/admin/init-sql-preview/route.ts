import { NextRequest, NextResponse } from "next/server";
import { execFile } from "child_process";
import { promisify } from "util";
import path from "path";
import fs from "fs";

const execFileAsync = promisify(execFile);

const BACKEND =
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

function repoRoot(): string {
  return path.join(process.cwd(), "..");
}

function pythonExecutable(): string {
  const venvPy = path.join(repoRoot(), "backend", ".venv", "Scripts", "python.exe");
  if (fs.existsSync(venvPy)) return venvPy;
  const venvPyUnix = path.join(repoRoot(), "backend", ".venv", "bin", "python");
  if (fs.existsSync(venvPyUnix)) return venvPyUnix;
  return process.platform === "win32" ? "python" : "python3";
}

async function verifyOrgAdmin(req: NextRequest): Promise<boolean> {
  const auth = req.headers.get("authorization");
  if (!auth) return false;
  try {
    const res = await fetch(`${BACKEND}/api/v1/database/admin/status`, {
      headers: { authorization: auth },
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  }
}

async function previewFromPython(schema: string, seedTestData: boolean) {
  const script = path.join(repoRoot(), "backend", "scripts", "preview_init_sql.py");
  const args = [script, "--schema", schema];
  if (!seedTestData) args.push("--no-seed");

  const { stdout } = await execFileAsync(pythonExecutable(), args, {
    cwd: path.join(repoRoot(), "backend"),
    env: { ...process.env, PYTHONPATH: path.join(repoRoot(), "backend") },
    maxBuffer: 16 * 1024 * 1024,
  });
  return JSON.parse(stdout) as Record<string, unknown>;
}

export async function GET(req: NextRequest) {
  if (!(await verifyOrgAdmin(req))) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const schema = req.nextUrl.searchParams.get("db_schema") || "public";
  const seedTestData = req.nextUrl.searchParams.get("seed_test_data") !== "false";

  try {
    const upstream = await fetch(
      `${BACKEND}/api/v1/database/admin/init-sql-preview${req.nextUrl.search}`,
      {
        headers: { authorization: req.headers.get("authorization") || "" },
        cache: "no-store",
      },
    );
    if (upstream.ok) {
      const body = await upstream.text();
      return new NextResponse(body, {
        status: upstream.status,
        headers: { "content-type": "application/json" },
      });
    }
    if (upstream.status !== 404) {
      const body = await upstream.text();
      return new NextResponse(body, { status: upstream.status });
    }
  } catch {
    /* fall through to local Python preview */
  }

  try {
    const data = await previewFromPython(schema, seedTestData);
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ detail: message }, { status: 502 });
  }
}
