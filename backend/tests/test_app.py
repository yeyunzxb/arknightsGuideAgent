import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk
from langchain_core.runnables import RunnableLambda

from app import main, rag
from app.knowledge import KnowledgeStore, parse_markdown


def document(title="测试干员", text="阿米娅是术师，这份资料用于验证检索。"):
    return f'''---
title: "{title}"
category: "干员"
tags: ["阿米娅", "术师"]
source: "测试资料"
updated: "2026-11-05"
server: "测试服"
---
{text}
'''


@pytest.fixture
def store(tmp_path):
    return KnowledgeStore(tmp_path)


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(main, "store", store)
    with TestClient(main.app) as client:
        yield client


def test_import_retrieval_restart_and_source(store):
    store.add("阿米娅.md", document())
    hits = store.search("阿米娅是什么职业")
    assert hits[0]["filename"] == "阿米娅.md"
    assert hits[0]["source"] == "测试资料"
    assert "术师" in hits[0]["text"]
    assert KnowledgeStore(store.directory).search("阿米娅")
    assert store.search("xyzxyzxyz") == []


def test_empty_index(store):
    assert store.stats()["documents"] == 0
    assert store.search("阿米娅") == []


@pytest.mark.parametrize("filename", ["../escape.md", "a/b.md", "C:\\escape.md", ".hidden.md", "file.txt"])
def test_path_validation(store, filename):
    with pytest.raises(ValueError):
        store.add(filename, document())


def test_no_overwrite(store):
    store.add("one.md", document())
    with pytest.raises(FileExistsError):
        store.add("one.md", document(text="覆盖"))
    assert "术师" in store.search("阿米娅")[0]["text"]


def test_bad_yaml_and_empty_body():
    with pytest.raises(ValueError):
        parse_markdown("没有头部", "a.md")
    with pytest.raises(ValueError):
        parse_markdown(document().replace('"2026-11-05"', '2026-11-05'), "a.md")
    with pytest.raises(ValueError):
        parse_markdown(document(text=""), "a.md")


def test_invalid_file_report_and_chunking(store):
    (store.directory / "bad.md").write_text("bad", encoding="utf-8")
    store.add("long.md", document(text="阿米娅术师的详细说明。" * 300))
    assert store.stats()["errors"][0]["filename"] == "bad.md"
    assert len(store.chunks) > 1
    assert all(len(c.page_content) <= 700 and "start_index" in c.metadata for c in store.chunks)


def test_routes_and_no_secret_echo(client):
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/knowledge", json={"filename": "test.md", "content": document()}).status_code == 200
    assert client.post("/api/knowledge", json={"filename": "test.md", "content": document()}).status_code == 409
    assert client.post("/api/knowledge/reindex").json()["documents"] == 1
    secret = "sk-private-example"
    response = client.post("/api/chat", json={"api_key": secret, "question": " "})
    assert response.status_code == 422
    assert secret not in response.text


def test_refusal_never_calls_model(client, monkeypatch):
    def fail(*args):
        pytest.fail("空知识库不应调用模型")
    monkeypatch.setattr(rag, "create_model", fail)
    response = client.post("/api/chat", json={"api_key": "sk-test-only", "question": "火星猫"})
    assert "资料不足" in response.text
    assert 'event: done' in response.text


def test_stream_prompt_history_and_citations(client, store, monkeypatch):
    store.add("amiya.md", document())
    received = []
    async def fake_stream(prompt):
        received.extend(prompt.to_messages())
        yield AIMessageChunk(content="阿米娅是")
        yield AIMessageChunk(content="术师。[1]")
    monkeypatch.setattr(rag, "create_model", lambda *args: RunnableLambda(fake_stream))
    response = client.post("/api/chat", json={"api_key": "sk-test-only", "question": "阿米娅是什么职业",
                                             "history": [{"role": "user", "content": "我想问干员问题"}]})
    frames = [f for f in response.text.split("\n\n") if f]
    sources = json.loads(frames[0].split("data: ")[1])
    assert sources[0]["citation"] == 1 and sources[0]["filename"] == "amiya.md"
    assert "术师。[1]" in response.text and "event: done" in response.text
    assert "amiya.md" in received[0].content
    assert received[1].content == "我想问干员问题"
    assert received[-1].content == "阿米娅是什么职业"


def test_model_error_is_redacted(client, store, monkeypatch):
    store.add("test.md", document())
    def fail(*args):
        raise RuntimeError("secret sk-test-only")
    monkeypatch.setattr(rag, "create_model", fail)
    response = client.post("/api/chat", json={"api_key": "sk-test-only", "question": "阿米娅"})
    assert "event: error" in response.text and "sk-test-only" not in response.text


def test_models_use_fixed_official_endpoint(client, monkeypatch):
    from functools import partial

    def handler(request):
        assert str(request.url) == "https://api.deepseek.com/models"
        assert request.headers["Authorization"] == "Bearer sk-test-only"
        return httpx.Response(200, json={"data": [{"id": "deepseek-flash", "name": "Flash"}]})
    monkeypatch.setattr(rag, "ChatOpenAI", partial(rag.ChatOpenAI,
                        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    assert client.post("/api/models", json={"api_key": "sk-test-only"}).json()["models"][0]["id"] == "deepseek-flash"


def test_model_list_network_failure_is_not_invalid_key(client, monkeypatch):
    from functools import partial

    def handler(request):
        raise httpx.ConnectError("private request context sk-test-only", request=request)
    monkeypatch.setattr(rag, "ChatOpenAI", partial(rag.ChatOpenAI,
                        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    response = client.post("/api/models", json={"api_key": "sk-test-only"})
    assert response.status_code == 502
    assert "模型列表获取失败" in response.text and "仍可" in response.text
    assert "密钥无效" not in response.text and "sk-test-only" not in response.text


def test_model_list_rejects_invalid_key_explicitly(client, monkeypatch):
    from functools import partial

    def handler(request):
        return httpx.Response(401, json={"error": {"message": "invalid key", "type": "authentication_error"}})
    monkeypatch.setattr(rag, "ChatOpenAI", partial(rag.ChatOpenAI,
                        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    response = client.post("/api/models", json={"api_key": "sk-test-only"})
    assert response.status_code == 502
    assert "API Key 无效或已失效" in response.text


def test_real_adapter_with_mock_upstream(client, store, monkeypatch):
    """使用真实 ChatOpenAI/LCEL/SDK，仅替换远端 HTTP，验证兼容协议。"""
    from functools import partial

    store.add("test.md", document())
    def handler(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        payload = json.loads(request.content)
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["stream"] is True
        assert payload["model"] == "deepseek-flash"
        assert "术师" in payload["messages"][0]["content"]
        body = 'data: ' + json.dumps({"id": "test", "object": "chat.completion.chunk", "created": 0, "model": "deepseek-flash", "choices": [{"index": 0, "delta": {"content": "术师。[1]"}, "finish_reason": None}]}) + '\n\ndata: [DONE]\n\n'
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text=body)
    monkeypatch.setattr(rag, "ChatOpenAI", partial(rag.ChatOpenAI,
                        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    response = client.post("/api/chat", json={"api_key": "sk-test-only", "question": "阿米娅是什么职业"})
    assert "event: done" in response.text and "术师。[1]" in response.text, response.text
