from backend.app.database import SessionLocal, UPLOAD_DIR
from backend.app.models import Chunk, Document, KnowledgeBase
from backend.app.services import knowledge
from backend.app.services.vector_store import (
    delete_document_points,
    ensure_collection,
    search_points,
    upsert_points,
)


def seed_document():
    with SessionLocal() as db:
        kb = KnowledgeBase(name="索引测试", chunk_size=100, chunk_overlap=10, min_chunk_chars=1)
        db.add(kb)
        db.flush()
        document = Document(
            knowledge_base_id=kb.id,
            filename="sample.txt",
            stored_name="sample.txt",
            content_type="text/plain",
            size=200,
        )
        db.add(document)
        db.commit()
        document_id = document.id
        kb_id = kb.id
    (UPLOAD_DIR / "sample.txt").write_text("第一段内容。\n\n第二段内容，用于测试重复索引。", encoding="utf-8")
    return kb_id, document_id


def test_indexing_is_idempotent(monkeypatch):
    kb_id, document_id = seed_document()
    calls = {"delete": 0, "upsert": 0}
    monkeypatch.setattr(
        knowledge,
        "embed_texts",
        lambda texts, **kwargs: [[0.1, 0.2, 0.3] for _ in texts],
    )
    monkeypatch.setattr(knowledge, "create_client", lambda *args, **kwargs: object())
    monkeypatch.setattr(knowledge, "ensure_collection", lambda *args: None)
    monkeypatch.setattr(
        knowledge,
        "delete_document_points",
        lambda *args: calls.__setitem__("delete", calls["delete"] + 1),
    )
    monkeypatch.setattr(
        knowledge,
        "upsert_points",
        lambda client, collection, points: calls.__setitem__("upsert", calls["upsert"] + 1),
    )

    knowledge.index_document(document_id, "embedding-key")
    with SessionLocal() as db:
        first_count = db.query(Chunk).filter(Chunk.document_id == document_id).count()
        assert db.get(Document, document_id).status == "completed"

    knowledge.index_document(document_id, "embedding-key")
    with SessionLocal() as db:
        second_count = db.query(Chunk).filter(Chunk.document_id == document_id).count()
        assert second_count == first_count
        assert db.get(Document, document_id).chunk_count == second_count
    assert calls == {"delete": 2, "upsert": 2}


def test_retrieval_returns_structured_sources(monkeypatch):
    kb_id, _ = seed_document()
    with SessionLocal() as db:
        kb = db.get(KnowledgeBase, kb_id)
        monkeypatch.setattr(knowledge, "embed_texts", lambda *args, **kwargs: [[0.1, 0.2]])
        monkeypatch.setattr(knowledge, "create_client", lambda *args, **kwargs: object())
        monkeypatch.setattr(
            knowledge,
            "search_points",
            lambda *args, **kwargs: [
                {
                    "id": "point-1",
                    "score": 0.91,
                    "payload": {
                        "document_name": "sample.txt",
                        "document_id": 1,
                        "chunk_id": 9,
                        "page": 3,
                        "content": "命中的片段",
                    },
                }
            ],
        )
        results = knowledge.retrieve(kb, "问题", embedding_api_key="key")
    assert results[0]["knowledge_base_id"] == kb_id
    assert results[0]["page"] == 3
    assert "[来源 1]" in knowledge.build_rag_context(results)


def test_chroma_search_filters_by_knowledge_base():
    class Collection:
        def query(self, **kwargs):
            assert kwargs["where"] == {"knowledge_base_id": 42}
            assert kwargs["n_results"] == 5
            return {
                "ids": [["point"]],
                "distances": [[0.12]],
                "documents": [["result"]],
                "metadatas": [[{"knowledge_base_id": 42}]],
            }

    class Client:
        def get_collection(self, name):
            assert name == "shared"
            return Collection()

    results = search_points(
        Client(), "shared", [0.1, 0.2], 42, limit=5, score_threshold=0.7
    )
    assert results[0]["id"] == "point"
    assert abs(results[0]["score"] - 0.88) < 1e-6


def test_chroma_local_index_filter_and_delete(tmp_path):
    import chromadb

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    ensure_collection(client, "shared", 2)
    upsert_points(
        client,
        "shared",
        [
            (
                "11111111-1111-1111-1111-111111111111",
                [1.0, 0.0],
                {"knowledge_base_id": 1, "document_id": 10, "content": "kb1"},
            ),
            (
                "22222222-2222-2222-2222-222222222222",
                [1.0, 0.0],
                {"knowledge_base_id": 2, "document_id": 20, "content": "kb2"},
            ),
        ],
    )
    results = search_points(
        client, "shared", [1.0, 0.0], 1, limit=5, score_threshold=0.5
    )
    assert [item["payload"]["content"] for item in results] == ["kb1"]

    delete_document_points(client, "shared", 1, 10)
    assert search_points(
        client, "shared", [1.0, 0.0], 1, limit=5, score_threshold=0.5
    ) == []
