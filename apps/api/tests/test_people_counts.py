"""Personas: cuántas reuniones y tareas tiene cada una (6/10: todas daban 0)."""
import uuid

from conftest import EchoTestUser
from test_levels import Member, _sql


def test_people_count_the_meetings_they_recorded_or_spoke_in_and_their_tasks(client):
    owner = EchoTestUser(client, name="Bauti Goñi", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    laura = Member(client, owner, "Laura")
    first = client.post("/api/meetings", json={"title": "Familia Romero"}, headers=owner.headers).json()
    client.post("/api/meetings", json={"title": "Familia Pérez"}, headers=owner.headers)
    # Laura no grabó: Echo la reconoció hablando en la primera.
    _sql("INSERT INTO speakers (id, meeting_id, label, display_name, user_id, color, created_at, updated_at)"
         " VALUES (gen_random_uuid(), :m, 'Persona 1', 'Laura', :u, '#6366f1', now(), now())",
         m=first["id"], u=laura.user_id)
    task = client.post("/api/tasks", json={"text": "Llamar a la familia", "meeting_id": first["id"]},
                       headers=owner.headers).json()
    client.patch(f"/api/tasks/{task['id']}", json={"assignee_user_id": laura.user_id}, headers=owner.headers)

    people = {p["name"]: p for p in client.get("/api/people", headers=owner.headers).json()}
    assert (people["Bauti Goñi"]["meeting_count"], people["Bauti Goñi"]["open_task_count"]) == (2, 0)
    assert (people["Laura"]["meeting_count"], people["Laura"]["open_task_count"]) == (1, 1)
    detail = client.get(f"/api/people/{laura.user_id}", headers=owner.headers).json()
    assert (detail["meeting_count"], detail["open_task_count"]) == (1, 1)
    assert [m["title"] for m in detail["meetings"]] == ["Familia Romero"]
