from backend.app import main
from backend.app.database import SessionLocal
from backend.app.models import KnowledgeBase


MODEL = {
    "provider": "openai",
    "name": "test-chat",
    "apiKey": "test-key",
    "baseUrl": "https://example.invalid/v1",
}


def test_chat_without_knowledge_base_remains_compatible(client, monkeypatch):
    async def fake_llm(**kwargs):
        assert kwargs["system_context"] == ""
        return "普通回答"

    monkeypatch.setattr(main, "call_llm", fake_llm)
    response = client.post("/api/chat", json={"message": "你好", "model": MODEL})
    assert response.status_code == 200
    assert response.json()["answer"] == "普通回答"
    assert response.json()["sources"] == []


def test_chat_injects_rag_context_and_sources(client, monkeypatch):
    with SessionLocal() as db:
        kb = KnowledgeBase(name="聊天知识库")
        db.add(kb)
        db.commit()
        kb_id = kb.id

    sources = [
        {
            "knowledge_base_id": kb_id,
            "document": "guide.pdf",
            "document_id": 2,
            "chunk_id": 3,
            "point_id": "p1",
            "page": 4,
            "sheet": None,
            "score": 0.93,
            "content": "可引用事实",
        }
    ]
    monkeypatch.setattr(main, "retrieve", lambda *args, **kwargs: sources)

    async def fake_llm(**kwargs):
        assert "[来源 1]" in kwargs["system_context"]
        return "基于知识库的回答 [来源 1]"

    monkeypatch.setattr(main, "call_llm", fake_llm)
    response = client.post(
        "/api/chat",
        json={
            "message": "问题",
            "model": MODEL,
            "knowledgeBaseId": kb_id,
            "embeddingApiKey": "embedding-key",
        },
    )
    assert response.status_code == 200
    assert response.json()["sources"][0]["document"] == "guide.pdf"
