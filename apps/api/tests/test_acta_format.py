"""Cómo se ve el acta: tamaño de letra, interlineado y márgenes por sede."""
import io
import uuid

from conftest import EchoTestUser


def _org_with_acta(client):
    user = EchoTestUser(client, name="Formato", org_name=f"Org Formato {uuid.uuid4().hex[:4]}")
    user.make_paid()
    meeting_id = client.post("/api/meetings", json={"title": "Acta"}, headers=user.headers).json()["id"]
    client.post(
        f"/api/meetings/{meeting_id}/minutes/versions",
        json={"body_markdown": "# Acta\n\n## Temas\n\nTexto del acta.\n\n- Un acuerdo."},
        headers=user.headers,
    )
    return user, meeting_id


def test_the_format_starts_as_always_and_is_saved_apart_from_the_letterhead(client):
    user, _ = _org_with_acta(client)
    letterhead = client.get("/api/org/letterhead", headers=user.headers).json()
    assert (letterhead["font_size"], letterhead["line_spacing"], letterhead["margins"]) == ("normal", "1.5", "normal")

    saved = client.put(
        "/api/org/letterhead/format",
        json={"font_size": "grande", "line_spacing": "simple", "margins": "angosto"},
        headers=user.headers,
    )
    assert saved.status_code == 200
    assert (saved.json()["font_size"], saved.json()["line_spacing"], saved.json()["margins"]) == (
        "grande", "simple", "angosto",
    )
    # Cambiar el formato no borra el membrete...
    client.put("/api/org/letterhead", json={"institution": "Colegio X", "font": "times"}, headers=user.headers)
    again = client.get("/api/org/letterhead", headers=user.headers).json()
    # ...y guardar el membrete no pisa el formato.
    assert again["institution"] == "Colegio X" and again["font"] == "times"
    assert again["font_size"] == "grande" and again["line_spacing"] == "simple" and again["margins"] == "angosto"
    client.put("/api/org/letterhead/format", json={"font_size": "muy_grande"}, headers=user.headers)
    assert client.get("/api/org/letterhead", headers=user.headers).json()["institution"] == "Colegio X"

    bad = client.put("/api/org/letterhead/format", json={"font_size": "gigante"}, headers=user.headers)
    assert bad.status_code == 422


def test_word_and_pdf_use_the_chosen_size(client):
    from docx import Document

    user, meeting_id = _org_with_acta(client)
    url = f"/api/meetings/{meeting_id}/export/minutes"

    normal = Document(io.BytesIO(client.get(f"{url}.docx", headers=user.headers).content))
    assert normal.styles["Normal"].font.size.pt == 11
    assert normal.styles["Normal"].paragraph_format.line_spacing == 1.5
    normal_pdf = client.get(f"{url}.pdf", headers=user.headers).content

    client.put(
        "/api/org/letterhead/format",
        json={"font_size": "grande", "line_spacing": "simple", "margins": "angosto"},
        headers=user.headers,
    )
    big = Document(io.BytesIO(client.get(f"{url}.docx", headers=user.headers).content))
    assert big.styles["Normal"].font.size.pt == 13
    assert big.styles["Normal"].paragraph_format.line_spacing == 1.0
    assert big.styles["Heading 2"].font.size.pt > normal.styles["Heading 2"].font.size.pt
    assert round(big.sections[0].left_margin.mm) == 13

    big_pdf = client.get(f"{url}.pdf", headers=user.headers).content
    assert _body_font(normal_pdf) == (b"10", b"15")  # 10 pt e interlineado 1,5
    assert _body_font(big_pdf) == (b"12", b"14.4")  # 12 pt, sencillo


def _body_font(pdf: bytes) -> tuple[bytes, bytes]:
    """(tamaño, interlineado) con que el PDF escribe el párrafo del acta."""
    import re

    found = re.search(rb"/F\d+ ([\d.]+) Tf ([\d.]+) TL \(Texto del acta", _pdf_text(pdf))
    assert found, "no se encontró el párrafo en el PDF"
    return found.group(1), found.group(2)


def _pdf_text(pdf: bytes) -> bytes:
    """Las órdenes de dibujo del PDF (ReportLab las guarda en ASCII85 + Flate)."""
    import base64
    import re
    import zlib

    streams = re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S)
    out = b""
    for raw in streams:
        try:
            out += zlib.decompress(base64.a85decode(raw.strip(), adobe=True))
        except Exception:
            continue
    return out


def test_only_admins_change_the_format(client):
    from test_acta_entrevista import _join_as_member

    owner, _ = _org_with_acta(client)
    member = _join_as_member(client, owner)
    denied = client.put("/api/org/letterhead/format", json={"font_size": "grande"}, headers=member.headers)
    assert denied.status_code == 403
    # Todos ven el formato: la hoja de impresión lo necesita.
    assert client.get("/api/org/letterhead", headers=member.headers).json()["font_size"] == "normal"
