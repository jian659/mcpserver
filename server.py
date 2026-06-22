"""
placeholder-mcp — cloud-ready MCP server (Remote streamable-HTTP)

跟 local 版的差別：
  1. transport：streamable-http（透過 module-level `app` 物件，由 uvicorn 命令列啟動）
  2. host=0.0.0.0、port 讀環境變數 PORT（雲端平台注入）
  3. 可開關的 Bearer token 認證中介層
  4. 信任反向代理的 host（修正 Render/Cloudflare 的 421 Invalid Host header）

部署啟動指令（Render 的 Start Command）：
    uvicorn server:app --host 0.0.0.0 --port $PORT --forwarded-allow-ips '*'
"""

import os
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

API_BASE_URL = os.environ.get("API_BASE_URL", "https://jsonplaceholder.typicode.com")
UPSTREAM_KEY = os.environ.get("UPSTREAM_API_KEY")     # 呼叫上游 API 用（placeholder 不需要）
SERVER_KEY = os.environ.get("API_KEY")                # 保護「你的 server」用的 token
TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "30"))

# 允許的 host：localhost + 你的雲端網域（可用環境變數覆蓋，逗號分隔）
ALLOWED_HOSTS = os.environ.get(
    "ALLOWED_HOSTS",
    "localhost:*,127.0.0.1:*,mcpserver-untx.onrender.com,*.onrender.com",
).split(",")

# 關鍵：在「建立 FastMCP 物件時」就傳入 transport_security，
# 否則 SDK 會在 __init__ 自動鎖成 localhost-only，造成雲端 421 Invalid Host header。
mcp = FastMCP(
    "placeholder-cloud",
    json_response=True,
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,   # 雲端由平台/認證層把關，這裡關掉 SDK 的 host 鎖
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=["*"],
    ),
)


async def _get(path: str):
    headers = {}
    if UPSTREAM_KEY:
        headers["Authorization"] = f"Bearer {UPSTREAM_KEY}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(f"{API_BASE_URL}{path}", headers=headers)
        r.raise_for_status()
        return r.json()


async def _post(path: str, payload: dict):
    headers = {"Content-Type": "application/json"}
    if UPSTREAM_KEY:
        headers["Authorization"] = f"Bearer {UPSTREAM_KEY}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{API_BASE_URL}{path}", json=payload, headers=headers)
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def list_posts(limit: int = 10) -> list:
    """列出貼文（預設前 10 篇）。"""
    data = await _get("/posts")
    return data[:limit]


@mcp.tool()
async def get_post(post_id: int) -> dict:
    """依 ID 取得單篇貼文。"""
    return await _get(f"/posts/{post_id}")


@mcp.tool()
async def create_post(title: str, body: str, user_id: int = 1) -> dict:
    """建立一篇新貼文。"""
    return await _post("/posts", {"title": title, "body": body, "userId": user_id})


@mcp.tool()
async def get_user(user_id: int) -> dict:
    """依 ID 取得使用者資料。"""
    return await _get(f"/users/{user_id}")


@mcp.tool()
async def list_comments(post_id: int) -> list:
    """取得某篇貼文的所有留言。"""
    return await _get(f"/posts/{post_id}/comments")


# ── 認證中介層：保護你的 server 不被任意呼叫 ──────────────
class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in ("/", "/health"):
            return await call_next(request)
        if SERVER_KEY:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {SERVER_KEY}":
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


# ── module-level app：供 uvicorn 以 `server:app` 啟動 ──────────────
app = mcp.streamable_http_app()
app.add_middleware(BearerAuthMiddleware)


# 本機直接 `python server.py` 也能跑（雲端則用上方 uvicorn 指令）
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        forwarded_allow_ips="*",
    )
