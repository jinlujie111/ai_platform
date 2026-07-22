def test_knowledge_ui_assets_are_served(client):
    html = client.get("/").text
    javascript = client.get("/static/app.js").text
    stylesheet = client.get("/static/styles.css").text

    assert 'id="chatKnowledgeBase"' in html
    assert 'id="knowledgeBaseList"' in html
    assert 'id="kbDetailPane"' in html
    assert ".doc,.txt" not in html
    assert "loadKnowledgeBases" in javascript
    assert "knowledgeBaseId" in javascript
    assert ".kb-self-workspace" in stylesheet
