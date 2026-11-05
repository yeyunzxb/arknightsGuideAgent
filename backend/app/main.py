import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .knowledge import KnowledgeStore
from .rag import DEFAULT_MODELS, create_model, public_error, stream_answer
from .schemas import ChatRequest, Credentials, KnowledgeInput

ROOT = Path(__file__).resolve().parents[2]
store = KnowledgeStore(Path(os.environ.get("KNOWLEDGE_DIR", ROOT / "knowledge")))
app = FastAPI(title="PRTS · 明日方舟 RAG", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
semaphore = asyncio.Semaphore(3)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Pydantic 默认错误可能包含原始 input；这里避免回显 api_key。
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
    ]})


@app.get("/api/health")
def health():
    stats = store.stats()
    return {"status": "ok", "documents": stats["documents"], "chunks": stats["chunks"]}


@app.get("/api/knowledge")
def knowledge():
    return store.stats()


@app.post("/api/knowledge/reindex")
def reindex():
    return store.rebuild()


@app.post("/api/knowledge")
def add_knowledge(body: KnowledgeInput):
    try:
        return store.add(body.filename, body.content)
    except FileExistsError:
        raise HTTPException(409, "同名文件已存在，请重命名后导入；也可以直接编辑本地文件并重建索引。")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/models")
async def models(body: Credentials):
    try:
        # 与对话使用同一 LangChain/SDK 客户端工厂、网络配置和 90 秒超时。
        # 仅查询列表，不调用生成接口、不消耗生成 token。
        model = create_model(body.api_key.get_secret_value(), DEFAULT_MODELS[0])
        data = await model.root_async_client.models.list()
        return {"models": [{"id": m.id, "name": getattr(m, "name", None) or m.id} for m in data.data
                           if m.id.startswith("deepseek-")]}
    except Exception as exc:
        raise HTTPException(502, "模型列表获取失败：" + public_error(exc)
                            + " 模型列表与对话是独立接口；你仍可选择已有模型尝试对话。")


@app.post("/api/chat")
async def chat(body: ChatRequest):
    async def generate():
        async with semaphore:
            async for item in stream_answer(body, store):
                yield item
    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
