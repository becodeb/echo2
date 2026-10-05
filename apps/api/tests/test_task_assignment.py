"""Tareas: las que detecta Echo van a quien grabó, que las reparte (5/10).

Quién dijo en la reunión que se encargaba queda como sugerencia y es el
responsable que va al acta.
"""
import asyncio
import uuid
from datetime import date

from conftest import EchoTestUser
from test_levels import Member, _sql_rows

from echo_api.services.pipeline import _persist_insights


def _insights(*tasks: tuple[str, str | None]) -> dict:
    return {"tasks": [{"text": text, "assignee": who} for text, who in tasks]}


def test_echo_tasks_go_to_who_recorded_and_can_be_handed_out(client):
    owner = EchoTestUser(client, name="Bauti Goñi", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    directora = Member(client, owner, "Laura")
    meeting = client.post("/api/meetings", json={"title": "Familia Romero"}, headers=owner.headers).json()
    meeting_id = uuid.UUID(meeting["id"])

    asyncio.run(_persist_insights(meeting_id, _insights(
        ("Coordinar reunión con la psicopedagoga", "Directora"),
        ("Mandar el informe a la familia", None),
    ), date(2026, 10, 5)))

    tasks = {t["text"]: t for t in client.get(f"/api/meetings/{meeting_id}/insights", headers=owner.headers).json()["action_items"]}
    coordinar = tasks["Coordinar reunión con la psicopedagoga"]
    assert coordinar["assignee_user_id"] == owner.user_id and coordinar["assignee_name"] == "Bauti Goñi"
    assert coordinar["suggested_assignee"] == "Directora"
    assert tasks["Mandar el informe a la familia"]["suggested_assignee"] is None
    # Todas en "Mi trabajo" de quien grabó.
    mine = {t["text"] for t in client.get("/api/tasks/my-work", headers=owner.headers).json()["tasks"]}
    assert mine == set(tasks)

    # La reparte: pasa a la directora con su nombre, y le llega el aviso.
    handed = client.patch(f"/api/tasks/{coordinar['id']}", json={"assignee_user_id": directora.user_id}, headers=owner.headers)
    assert handed.status_code == 200, handed.text
    assert handed.json()["assignee_name"] == "Laura"
    assert handed.json()["suggested_assignee"] == "Directora"
    assert [t["text"] for t in client.get("/api/tasks/my-work", headers=directora.headers).json()["tasks"]] == [
        "Coordinar reunión con la psicopedagoga"
    ]
    [(kind,)] = _sql_rows("SELECT kind FROM notifications WHERE user_id = :u", u=directora.user_id)
    assert kind == "task_assigned"

    # Si la pasada final se vuelve a correr, la repartida no se pierde ni se duplica.
    asyncio.run(_persist_insights(meeting_id, _insights(
        ("Coordinar reunión con la psicopedagoga", "Directora"),
        ("Mandar el informe a la familia", None),
    ), date(2026, 10, 5)))
    after = client.get(f"/api/meetings/{meeting_id}/insights", headers=owner.headers).json()["action_items"]
    assert sorted((t["text"], t["assignee_name"]) for t in after) == [
        ("Coordinar reunión con la psicopedagoga", "Laura"),
        ("Mandar el informe a la familia", "Bauti Goñi"),
    ]


def test_a_task_cannot_go_to_someone_outside_the_school(client):
    owner = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    stranger = EchoTestUser(client, org_name=f"Otro {uuid.uuid4().hex[:4]}")
    task = client.post("/api/tasks", json={"text": "Llamar a la familia"}, headers=owner.headers).json()
    # Sin responsable, es de quien la crea.
    assert task["assignee_user_id"] == owner.user_id
    moved = client.patch(f"/api/tasks/{task['id']}", json={"assignee_user_id": stranger.user_id}, headers=owner.headers)
    assert moved.status_code == 400
