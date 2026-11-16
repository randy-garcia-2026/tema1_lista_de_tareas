import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import src.database as database

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    from src.main import app

    with TestClient(app) as c:
        yield c


def create(client, title="Tarea", description=None):
    r = client.post("/api/todos", json={"title": title, "description": description})
    assert r.status_code == 201
    return r.json()


def test_create_todo(client):
    r = client.post("/api/todos", json={"title": "Comprar pan", "description": "integral"})
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Comprar pan"
    assert data["description"] == "integral"
    assert data["status"] == "pending"
    assert isinstance(data["id"], int)


def test_create_todo_without_description(client):
    assert create(client)["description"] is None


def test_create_todo_invalid(client):
    assert client.post("/api/todos", json={"title": ""}).status_code == 422
    assert client.post("/api/todos", json={}).status_code == 422
    assert client.post("/api/todos", json={"title": "   "}).status_code == 422


def test_list_todos(client):
    assert client.get("/api/todos").json() == []
    create(client, "a")
    create(client, "b")
    r = client.get("/api/todos")
    assert r.status_code == 200
    assert [t["title"] for t in r.json()] == ["a", "b"]


def test_list_todos_filter_status(client):
    t1 = create(client, "a")
    create(client, "b")
    client.patch(f"/api/todos/{t1['id']}", json={"status": "done"})
    done = client.get("/api/todos", params={"status": "done"}).json()
    pending = client.get("/api/todos", params={"status": "pending"}).json()
    assert [t["title"] for t in done] == ["a"]
    assert [t["title"] for t in pending] == ["b"]
    assert client.get("/api/todos", params={"status": "otro"}).status_code == 422


def test_get_todo(client):
    t = create(client, "x")
    r = client.get(f"/api/todos/{t['id']}")
    assert r.status_code == 200
    assert r.json() == t


def test_get_todo_not_found(client):
    r = client.get("/api/todos/999")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_update_todo(client):
    t = create(client, "viejo", "desc")
    r = client.patch(f"/api/todos/{t['id']}", json={"title": "nuevo", "status": "done"})
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "nuevo"
    assert data["status"] == "done"
    assert data["description"] == "desc"  # no modificado


def test_update_todo_clear_description(client):
    t = create(client, "x", "desc")
    r = client.patch(f"/api/todos/{t['id']}", json={"description": None})
    assert r.json()["description"] is None


def test_update_todo_errors(client):
    t = create(client)
    assert client.patch("/api/todos/999", json={"title": "x"}).status_code == 404
    assert client.patch(f"/api/todos/{t['id']}", json={"status": "bad"}).status_code == 422
    assert client.patch(f"/api/todos/{t['id']}", json={"title": None}).status_code == 422


def test_delete_todo(client):
    t = create(client)
    assert client.delete(f"/api/todos/{t['id']}").status_code == 204
    assert client.get(f"/api/todos/{t['id']}").status_code == 404


def test_delete_todo_not_found(client):
    assert client.delete("/api/todos/999").status_code == 404
