"""Benchmark de rendimiento de la API con datos de tamaño real.

Siembra (una sola vez) una sede con 60 reuniones y una larga de 1100 frases con
embeddings de 1536 dimensiones, como las de producción, y mide los endpoints
que abre la app: arranque, listas, una reunión vieja y su transcript.

    DATABASE_URL=postgresql+asyncpg://echo:echo_dev_pw@localhost:5433/echo \
        python bench/perf_bench.py [--runs 15]

Corre en proceso (httpx.ASGITransport): mide el servidor, sin red. La cuenta
sembrada (perf-bench@echodemo.dev, contraseña local BENCH_PASSWORD) sirve para
medir la web contra la API local.
"""
import argparse
import asyncio
import random
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import event, select

from echo_api.db import SessionLocal, engine
from echo_api.main import app
from echo_api.models import (
    Meeting,
    Organization,
    OrganizationMember,
    SharedLink,
    TranscriptSegment,
    User,
)
from echo_api.models.meetings import EMBEDDING_DIM
from echo_api.security import create_access_token, hash_password

EMAIL = "perf-bench@echodemo.dev"
BENCH_PASSWORD = "bench-local-1234"  # solo la base local de desarrollo
SEGMENTS = 1100
MEETINGS = 60

_queries = {"n": 0}


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _count(*_args):
    _queries["n"] += 1


async def seed() -> tuple[User, Organization, Meeting, str]:
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == EMAIL))).scalar_one_or_none()
        if user:
            if not user.password_hash:
                user.password_hash = hash_password(BENCH_PASSWORD)
                await db.commit()
            member = (await db.execute(select(OrganizationMember).where(OrganizationMember.user_id == user.id))).scalar_one()
            org = await db.get(Organization, member.organization_id)
            big = (await db.execute(
                select(Meeting).where(Meeting.organization_id == org.id).order_by(Meeting.created_at).limit(1)
            )).scalar_one()
            token = (await db.execute(select(SharedLink.token).where(SharedLink.meeting_id == big.id))).scalar_one()
            return user, org, big, token
        user = User(email=EMAIL, name="Bench", password_hash=hash_password(BENCH_PASSWORD))
        org = Organization(name="Bench", slug=f"bench-{uuid.uuid4().hex[:6]}", plan="cortesia")
        db.add_all([user, org])
        await db.flush()
        db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
        start = datetime.now(UTC) - timedelta(days=MEETINGS)
        meetings = []
        for index in range(MEETINGS):
            meeting = Meeting(
                organization_id=org.id, created_by=user.id, title=f"Reunión {index}", status="completed",
                kind="familia", level="primaria", started_at=start + timedelta(days=index),
                duration_seconds=3600, language="es",
            )
            meeting.created_at = start + timedelta(days=index)
            meetings.append(meeting)
        db.add_all(meetings)
        await db.flush()
        big = meetings[0]  # la más vieja: "contenido antiguo"
        rng = random.Random(1)
        for seq in range(1, SEGMENTS + 1):
            db.add(TranscriptSegment(
                meeting_id=big.id, organization_id=org.id, seq=seq, start_ms=seq * 3000, end_ms=seq * 3000 + 2800,
                text="Se conversa sobre el seguimiento pedagógico del estudiante y los acuerdos con la familia. " * 2,
                is_final=True, embedding=[rng.uniform(-1, 1) for _ in range(EMBEDDING_DIM)],
            ))
        token = f"bench-{uuid.uuid4().hex}"
        db.add(SharedLink(meeting_id=big.id, organization_id=org.id, token=token, role="viewer",
                          created_by=user.id, expires_at=datetime.now(UTC) + timedelta(days=3650)))
        await db.commit()
        return user, org, big, token


async def main(runs: int) -> None:
    user, org, big, token = await seed()
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}", "X-Organization-Id": str(org.id)}
    paths = [
        ("arranque: /api/auth/me", "/api/auth/me"),
        ("inicio: /api/dashboard", "/api/dashboard"),
        ("reuniones: lista", "/api/meetings?kind=familia"),
        ("reuniones: página vieja", "/api/meetings?kind=familia&offset=30"),
        ("reunión vieja", f"/api/meetings/{big.id}"),
        ("transcript p1 (300)", f"/api/meetings/{big.id}/transcript?after_seq=0&limit=300"),
        ("transcript p4 (300)", f"/api/meetings/{big.id}/transcript?after_seq=900&limit=300"),
        ("vista compartida", f"/api/shared/{token}"),
    ]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://bench", headers=headers, timeout=120) as client:
        await client.get("/api/auth/me")
        print(f"{'pantalla':28} {'p50 ms':>8} {'p90 ms':>8} {'KB':>7} {'SQL':>4}")
        for label, path in paths:
            times = []
            for _ in range(runs):
                _queries["n"] = 0
                t = time.perf_counter()
                response = await client.get(path)
                times.append((time.perf_counter() - t) * 1000)
            assert response.status_code == 200, (path, response.status_code, response.text[:200])
            times.sort()
            print(f"{label:28} {statistics.median(times):8.1f} {times[int(len(times) * 0.9) - 1]:8.1f} "
                  f"{len(response.content) / 1024:7.1f} {_queries['n']:4}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=15)
    asyncio.run(main(parser.parse_args().runs))
