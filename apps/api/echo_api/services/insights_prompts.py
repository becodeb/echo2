"""Prompts de extracción de información. Todos exigen evidencia (timestamps)
y prohíben inventar: si algo no está en el transcript, no se reporta.
"""

LIVE_EXTRACT_SYSTEM = """Sos el motor de análisis de Echo, un sistema de actas de reunión.
Analizás fragmentos de transcript EN VIVO y extraés SOLO información explícita.

REGLAS ESTRICTAS:
- NUNCA inventes información que no esté dicha textualmente en el fragmento.
- Cada item debe incluir evidence_start_ms y evidence_end_ms tomados de los timestamps [MM:SS] del fragmento (convertidos a milisegundos).
- No repitas decisiones ni tareas que ya están en la lista de "ya detectados".
- Si el fragmento no contiene nada nuevo, devolvé listas vacías.
- Respondé en el idioma del transcript."""


def build_live_extract_prompt(window_text: str, existing_decisions: list[str], existing_tasks: list[str]) -> str:
    existing = ""
    if existing_decisions:
        existing += "\nDecisiones ya detectadas:\n" + "\n".join(f"- {d}" for d in existing_decisions)
    if existing_tasks:
        existing += "\nTareas ya detectadas:\n" + "\n".join(f"- {t}" for t in existing_tasks)
    return f"""Fragmento nuevo del transcript (con timestamps [MM:SS]):

{window_text}
{existing}

Extraé la información NUEVA de este fragmento. Formato JSON:
{{
  "decisions": [{{"text": "...", "context": "por qué (si se dijo)", "evidence_start_ms": 0, "evidence_end_ms": 0}}],
  "tasks": [{{"text": "...", "assignee": "nombre o null", "due": "expresión de fecha textual o null", "evidence_start_ms": 0, "evidence_end_ms": 0}}],
  "questions": [{{"text": "...", "evidence_start_ms": 0, "evidence_end_ms": 0}}]
}}"""


FINAL_EXTRACT_SYSTEM = """Sos el motor de análisis post-reunión de Echo.
Recibís el transcript COMPLETO de una reunión con timestamps y hablantes,
y extraés información estructurada.

REGLAS ESTRICTAS:
- NUNCA inventes información. Todo item debe estar respaldado por el transcript.
- Cada item incluye evidence_start_ms/evidence_end_ms (convertí [MM:SS] a milisegundos).
- Las fechas van con su expresión TEXTUAL original en "due" (ej: "viernes", "15 de septiembre").
- Consolidá duplicados: si algo se dijo dos veces, un solo item con la mejor evidencia.
- Respondé en el idioma del transcript."""


def build_final_extract_prompt(transcript_text: str, bookmarks_text: str) -> str:
    bookmarks_block = ""
    if bookmarks_text:
        bookmarks_block = f"""
Marcadores manuales del usuario durante la reunión (dales prioridad):
{bookmarks_text}
"""
    return f"""Transcript completo:

{transcript_text}
{bookmarks_block}
Devolvé JSON con TODA la información estructurada de la reunión:
{{
  "topics": [{{"title": "...", "summary": "1-2 frases", "start_ms": 0, "end_ms": 0}}],
  "decisions": [{{"text": "...", "context": "por qué", "evidence_start_ms": 0, "evidence_end_ms": 0}}],
  "tasks": [{{"text": "...", "assignee": "nombre o null", "due": "texto o null", "evidence_start_ms": 0, "evidence_end_ms": 0}}],
  "questions": [{{"text": "...", "evidence_start_ms": 0, "evidence_end_ms": 0}}],
  "risks": [{{"text": "...", "evidence_start_ms": 0, "evidence_end_ms": 0}}],
  "mentions": {{
    "people": ["nombres de personas mencionadas"],
    "projects": ["proyectos mencionados"],
    "dates": [{{"text": "expresión", "context": "a qué refiere"}}],
    "numbers": [{{"text": "cifra", "context": "a qué refiere"}}],
    "links": ["urls mencionadas"]
  }},
  "timeline": [{{"at_ms": 0, "label": "momento importante (3-6 palabras)"}}],
  "next_steps": ["próximos pasos explícitos"]
}}"""


SUMMARY_SYSTEM = """Sos el redactor de resúmenes de Echo. Escribís resúmenes fieles
de reuniones basados EXCLUSIVAMENTE en el transcript. No agregues conocimiento
externo ni supongas nada que no se haya dicho. Respondé en {language}."""


def build_summary_prompt(transcript_text: str, insights_json: str) -> str:
    return f"""Transcript de la reunión:

{transcript_text}

Información estructurada ya extraída (para consistencia):
{insights_json}

Devolvé JSON:
{{
  "executive": ["5 a 10 puntos clave, una frase cada uno"],
  "detailed": "resumen extenso en markdown, organizado por temas, fiel al transcript"
}}"""


SECTION_SUMMARY_SYSTEM = """Resumís una sección de una reunión larga. Fidelidad absoluta
al texto: sin inventos ni conocimiento externo. Respondé en el idioma del transcript."""


def build_section_summary_prompt(section_text: str) -> str:
    return f"""Sección del transcript:

{section_text}

Devolvé JSON: {{"summary": "resumen fiel de 3-6 frases", "topics": ["temas tratados"]}}"""
