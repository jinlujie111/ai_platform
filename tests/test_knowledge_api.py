import json
from pathlib import Path

from backend.app import knowledge_api
from backend.app.database import SessionLocal, UPLOAD_DIR
from backend.app.models import Chunk, Document


def create_kb(client, name="测试知识库"):
    response = client.post("/api/knowledge-bases", json={"name": name, "description": "说明"})
    assert response.status_code == 201
    return response.json()


def test_knowledge_base_crud(client, monkeypatch):
    created = create_kb(client)
    listed = client.get("/api/knowledge-bases").json()
    assert listed[0]["name"] == "测试知识库"

    response = client.put(
        f"/api/knowledge-bases/{created['id']}",
        json={"description": "更新", "top_k": 8},
    )
    assert response.status_code == 200
    assert response.json()["top_k"] == 8

    monkeypatch.setattr(knowledge_api, "create_client", lambda *args, **kwargs: object())
    monkeypatch.setattr(knowledge_api, "delete_knowledge_base_points", lambda *args: None)
    assert client.delete(f"/api/knowledge-bases/{created['id']}").status_code == 204
    assert client.get("/api/knowledge-bases").json() == []


def test_upload_rejects_legacy_office_format(client):
    kb = create_kb(client)
    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/documents",
        files={"file": ("legacy.doc", b"legacy", "application/msword")},
    )
    assert response.status_code == 415


def test_upload_and_chunk_pagination(client, monkeypatch):
    kb = create_kb(client)
    monkeypatch.setattr(knowledge_api, "index_document", lambda *args, **kwargs: None)
    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/documents",
        files={"file": ("notes.txt", "hello world".encode(), "text/plain")},
        data={"embedding_api_key": "test"},
    )
    assert response.status_code == 202
    document_id = response.json()["id"]

    with SessionLocal() as db:
        document = db.get(Document, document_id)
        uploaded_path = UPLOAD_DIR / document.stored_name
        assert uploaded_path.exists()
        chunk = Chunk(
            knowledge_base_id=kb["id"],
            document_id=document_id,
            position=0,
            content="hello searchable world",
            source_metadata=json.dumps({"page": 2}),
            point_id="11111111-1111-1111-1111-111111111111",
        )
        db.add(chunk)
        document.chunk_count = 1
        db.commit()

    result = client.get(
        f"/api/knowledge-bases/{kb['id']}/chunks",
        params={"search": "searchable", "page": 1, "page_size": 10},
    ).json()
    assert result["total"] == 1
    assert result["items"][0]["metadata"]["page"] == 2

    monkeypatch.setattr(knowledge_api, "create_client", lambda *args, **kwargs: object())
    monkeypatch.setattr(knowledge_api, "delete_document_points", lambda *args: None)
    assert client.delete(
        f"/api/knowledge-bases/{kb['id']}/documents/{document_id}"
    ).status_code == 204
    assert not uploaded_path.exists()
    assert client.get(f"/api/knowledge-bases/{kb['id']}/chunks").json()["total"] == 0
