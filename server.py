"""
placeholder-mcp — cloud-ready MCP server (Remote streamable-HTTP)

跟 local 版的差別只有三點：
  1. transport 改成 streamable-http
  2. host=0.0.0.0、port 讀環境變數 PORT（雲端平台會注入）
  3. 加上一個可開關的 Bearer token 認證中介層

把 API_KEY 環境變數設好就會啟用認證；不設則開放（僅建議本機測試用）。
"""

import os
import httpx
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

API_BASE_URL = os.environ.get("API_BASE_URL", "https://jsonplaceholder.typicode.com")
UPSTREAM_KEY = os.environ.get("UPSTREAM_API_KEY")     # 呼叫上游 API 用（placeholder 不需要）
SERVER_KEY = os.environ.get("API_KEY")                # 保護「你的 server」用的 token
TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "30"))

mcp = FastMCP("placeholder-cloud", json_response=True, stateless_http=True)


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
        # 健康檢查端點放行（讓雲端平台能 ping）
        if request.url.path in ("/", "/health"):
            return await call_next(request)
        if SERVER_KEY:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {SERVER_KEY}":
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


if __name__ == "__main__":
    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware)

    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
