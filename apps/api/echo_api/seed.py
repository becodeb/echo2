"""Seed opcional de desarrollo: empresa ficticia con reuniones, decisiones y
tareas. La app NO depende de este seed.

Uso:
    docker compose exec api python -m echo_api.seed

Crea (si no existen):
    usuario  demo@echodemo.dev  /  contraseña  demo1234
    organización «Vega Estudio» con reuniones de ejemplo
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from .db import SessionLocal
from .models import (
    ActionItem,
    Decision,
    Meeting,
    MeetingParticipant,
    MeetingSummary,
    Organization,
    OrganizationMember,
    Project,
    ProjectMeeting,
    Question,
    Speaker,
    TranscriptSegment,
    User,
)
from .security import hash_password

DEMO_EMAIL = "demo@echodemo.dev"
DEMO_PASSWORD = "demo1234"

TRANSCRIPT_1 = [
    ("Ana", 0, "Buenas tardes a todos, arranquemos con el estado del proyecto DOE."),
    ("Marcos", 6, "El proveedor confirmó que la entrega se retrasa dos semanas."),
    ("Ana", 14, "Entonces movemos el lanzamiento de DOE al quince de octubre."),
    ("Julia", 22, "De acuerdo. Yo aviso al equipo de marketing hoy mismo."),
    ("Marcos", 29, "Queda pendiente saber cuánto cuesta la licencia anual del software nuevo."),
    ("Ana", 37, "Marcos, ¿podés pedir tres presupuestos para el viernes?"),
    ("Marcos", 43, "Sí, me encargo de los presupuestos esta semana."),
    ("Ana", 49, "Perfecto. Última cosa: el presupuesto de compras quedó aprobado."),
]

TRANSCRIPT_2 = [
    ("Ana", 0, "Seguimiento rápido de DOE. ¿Cómo venimos con los presupuestos?"),
    ("Marcos", 7, "Ya tengo dos presupuestos, el tercero llega mañana."),
    ("Ana", 14, "Bien. Confirmamos entonces el lanzamiento para el quince de octubre."),
    ("Julia", 21, "Marketing ya está trabajando con esa fecha."),
    ("Ana", 27, "Decidido: la campaña arranca el primero de octubre."),
]


async def seed() -> None:
    async with SessionLocal() as db:
        existing = (
            await db.execute(select(User).where(User.email == DEMO_EMAIL))
        ).scalar_one_or_none()
        if existing:
            print(f"El seed ya existe ({DEMO_EMAIL}); nada que hacer.")
            return

        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            name="Demo Echo",
            avatar_color="#6366f1",
        )
        db.add(user)
        await db.flush()

        org = Organization(name="Vega Estudio", slug=f"vega-{uuid.uuid4().hex[:6]}")
        db.add(org)
        await db.flush()
        db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))

        project = Project(
            organization_id=org.id, name="DOE", description="Lanzamiento del producto DOE",
            color="#0ea5e9",
        )
        db.add(project)
        await db.flush()

        now = datetime.now(UTC)

        async def build_meeting(title, days_ago, transcript, decisions, tasks, questions, summary_points):
            started = now - timedelta(days=days_ago, hours=2)
            duration = transcript[-1][1] + 8
            meeting = Meeting(
                organization_id=org.id,
                created_by=user.id,
                title=title,
                status="completed",
                started_at=started,
                ended_at=started + timedelta(seconds=duration),
                duration_seconds=duration,
                meta={
                    "visibility": "org",
                    "timeline": [{"at_ms": 0, "label": "Inicio"}] + [
                        {"at_ms": seconds * 1000, "label": text[:40]}
                        for _, seconds, text in transcript[2:4]
                    ],
                    "next_steps": ["Revisar presupuestos", "Confirmar fecha con marketing"],
                },
                processing_state={"stage": "done", "progress": 100, "skipped": ["seed"]},
            )
            db.add(meeting)
            await db.flush()
            db.add(ProjectMeeting(project_id=project.id, meeting_id=meeting.id))

            speaker_map = {}
            colors = ["#6366f1", "#0ea5e9", "#10b981"]
            for index, name in enumerate(dict.fromkeys(n for n, _, _ in transcript)):
                speaker = Speaker(
                    meeting_id=meeting.id,
                    label=f"Speaker {index + 1}",
                    display_name=name,
                    color=colors[index % len(colors)],
                )
                db.add(speaker)
                await db.flush()
                speaker_map[name] = speaker.id
                db.add(MeetingParticipant(meeting_id=meeting.id, name=name))

            for seq, (name, seconds, text) in enumerate(transcript, start=1):
                db.add(
                    TranscriptSegment(
                        meeting_id=meeting.id,
                        organization_id=org.id,
                        seq=seq,
                        speaker_id=speaker_map[name],
                        start_ms=seconds * 1000,
                        end_ms=seconds * 1000 + 5000,
                        text=text,
                        confidence=0.94,
                        is_final=True,
                    )
                )

            for text, evidence_seconds, context in decisions:
                db.add(
                    Decision(
                        meeting_id=meeting.id, organization_id=org.id, text=text,
                        context=context, evidence_start_ms=evidence_seconds * 1000,
                        evidence_end_ms=evidence_seconds * 1000 + 5000,
                    )
                )
            for text, assignee, due_text, due_date in tasks:
                db.add(
                    ActionItem(
                        meeting_id=meeting.id, organization_id=org.id, text=text,
                        assignee_name=assignee, due_text=due_text, due_date=due_date,
                        evidence_start_ms=40_000,
                    )
                )
            for text in questions:
                db.add(
                    Question(
                        meeting_id=meeting.id, organization_id=org.id, text=text,
                        evidence_start_ms=29_000,
                    )
                )
            db.add(
                MeetingSummary(
                    meeting_id=meeting.id, organization_id=org.id, kind="executive",
                    content={"points": summary_points}, model_used="seed",
                )
            )
            return meeting

        await build_meeting(
            "Reunión de dirección — DOE",
            7,
            TRANSCRIPT_1,
            [
                ("El lanzamiento de DOE se mueve al 15 de octubre", 14, "El proveedor retrasó la entrega dos semanas"),
                ("El presupuesto de compras queda aprobado", 49, None),
            ],
            [("Pedir tres presupuestos de la licencia", "Marcos", "viernes", (now - timedelta(days=4)).date())],
            ["¿Cuánto cuesta la licencia anual del software nuevo?"],
            [
                "El proveedor retrasó la entrega: DOE se lanza el 15 de octubre",
                "Marcos pedirá tres presupuestos de la licencia",
                "El presupuesto de compras quedó aprobado",
            ],
        )
        await build_meeting(
            "Seguimiento DOE",
            2,
            TRANSCRIPT_2,
            [
                ("Se confirma el lanzamiento de DOE para el 15 de octubre", 14, None),
                ("La campaña de marketing arranca el 1 de octubre", 27, None),
            ],
            [("Conseguir el tercer presupuesto", "Marcos", "mañana", (now - timedelta(days=1)).date())],
            [],
            [
                "Lanzamiento de DOE confirmado para el 15 de octubre",
                "La campaña de marketing arranca el 1 de octubre",
            ],
        )

        await db.commit()
        print("Seed creado:")
        print(f"  usuario:    {DEMO_EMAIL}")
        print(f"  contraseña: {DEMO_PASSWORD}")
        print("  organización «Vega Estudio» con 2 reuniones del proyecto DOE")


if __name__ == "__main__":
    asyncio.run(seed())
