import { NextRequest, NextResponse } from "next/server";

const BACKEND =
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

/** FastAPI list routes use trailing slash; Next.js strips it from incoming URLs. */
const COLLECTION_ROOTS = new Set([
  "agents",
  "employees",
  "skills",
  "workflows",
  "knowledge",
  "tools",
  "models",
  "orchestrator",
  "chat",
]);

function buildUpstreamPath(pathSegments: string[]): string {
  const subPath = pathSegments.map(encodeURIComponent).join("/");
  if (pathSegments.length === 1 && COLLECTION_ROOTS.has(pathSegments[0])) {
    return `${subPath}/`;
  }
  return subPath;
}

async function proxyRequest(req: NextRequest, pathSegments: string[]) {
  const subPath = buildUpstreamPath(pathSegments);
  const url = `${BACKEND}/api/v1/${subPath}${req.nextUrl.search}`;

  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const authorization = req.headers.get("authorization");
  if (authorization) headers.set("authorization", authorization);
  const accept = req.headers.get("accept");
  if (accept) headers.set("accept", accept);

  const init: RequestInit = {
    method: req.method,
    headers,
    cache: "no-store",
    signal: AbortSignal.timeout(120_000),
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }

  const upstream = await fetch(url, init).catch((err: unknown) => {
    const message = err instanceof Error ? err.message : "upstream fetch failed";
    return new Response(
      JSON.stringify({
        detail: `Backend unreachable at ${BACKEND}: ${message}`,
      }),
      { status: 502, headers: { "content-type": "application/json" } },
    );
  });
  const responseHeaders = new Headers();
  const upstreamType = upstream.headers.get("content-type");
  if (upstreamType) responseHeaders.set("content-type", upstreamType);
  const disposition = upstream.headers.get("content-disposition");
  if (disposition) responseHeaders.set("content-disposition", disposition);
  const contentLength = upstream.headers.get("content-length");
  if (contentLength) responseHeaders.set("content-length", contentLength);

  if (upstreamType?.includes("text/event-stream") && upstream.body) {
    responseHeaders.set("cache-control", "no-cache");
    responseHeaders.set("connection", "keep-alive");
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  }

  const body = await upstream.arrayBuffer();

  return new NextResponse(body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

type RouteContext = { params: { path: string[] } };

export async function GET(req: NextRequest, ctx: RouteContext) {
  return proxyRequest(req, ctx.params.path);
}

export async function POST(req: NextRequest, ctx: RouteContext) {
  return proxyRequest(req, ctx.params.path);
}

export async function PATCH(req: NextRequest, ctx: RouteContext) {
  return proxyRequest(req, ctx.params.path);
}

export async function PUT(req: NextRequest, ctx: RouteContext) {
  return proxyRequest(req, ctx.params.path);
}

export async function DELETE(req: NextRequest, ctx: RouteContext) {
  return proxyRequest(req, ctx.params.path);
}

export async function OPTIONS(req: NextRequest, ctx: RouteContext) {
  return proxyRequest(req, ctx.params.path);
}
