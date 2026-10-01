# Echo: plan de correcciones (privacidad, plata, landing, app)

Escrito el 1/10/2026 para que una sesión nueva lo implemente sin contexto
previo. **Lo que se haga acá va a producción**: commits chicos con tests,
`main` limpio, y **confirmar con Bauti (el dueño) antes de cada deploy**. Si una
decisión no está en este documento, **preguntarle a Bauti antes de decidir**.

---

## 0. Contexto desde cero

**Qué es Echo.** https://echo.becode.com.ar. Graba reuniones de colegios
(entrevistas con familias, reuniones de equipo) y de personas individuales:
transcribe en vivo, al finalizar separa quién habló, genera acta (con membrete),
resumen, tareas con responsables, memoria de la sede, chat con IA y
**"Hablar con Echo"** (conversación por voz, plan Individual + voz). Público:
directivos y docentes en Argentina, castellano rioplatense.

**Repo.** `github.com/becodeb/echo2`, rama `main` (= producción, commit
`7e5d061` al escribir esto). Monorepo:
- `apps/api`: FastAPI + SQLAlchemy async + Postgres 17/pgvector. Migraciones en
  `apps/api/alembic/versions` (idempotentes y reversibles, como 0016-0018).
- `apps/web`: React + Vite + TypeScript + Tailwind. Se instala con **pnpm**
  (`pnpm install --frozen-lockfile && pnpm build`), igual que el Dockerfile.
- `apps/bridge` (Rust, motor local), `apps/video` (Remotion, no se despliega).

**Leer antes de tocar nada:** `README.md`, `docs/architecture.md`,
`docs/security.md` y **`docs/plan-transcripcion-y-planes.md`** (el plan anterior,
ya implementado: proveedores, planes, créditos, menores, consumo).

**Cómo está armado hoy (resumen):**
- En vivo: Groq `whisper-large-v3-turbo` sin pista de contexto
  (`routers/live.py`, `services/stt/*`).
- Pasada final: ElevenLabs Scribe v2 (texto + quién habló + entidades) si el plan
  o un crédito lo cubre y la reunión **no** tiene menores; si no, Groq
  (`services/diarization.py`, `services/plans.py`).
- Privacidad: `services/privacy.py` reemplaza nombres y datos por marcadores
  antes del LLM; la IA de actas/chat es OpenAI (`gpt-6-luna` por defecto) o Groq
  (`openai/gpt-oss-120b`).
- Planes (pantalla `apps/web/src/pages/Plans.tsx`): Gratis US$0 (4 reuniones/mes
  con quién habló, por docente), Individual US$5 (5 h/mes con quién habló),
  Individual + voz US$10 (**60 min/mes** de voz), Instituciones "A medida"
  (Contact sales). Sin links de pago: los botones avisan a Becode. Northfield
  está en "Cortesía" (no paga). Superadmins: becodestudio@gmail.com y
  gonibauti@gmail.com (`SUPERADMIN_EMAILS`).
- Consumo: `routers/billing.py`, `routers/admin_billing.py`, `services/plans.py`;
  pantalla "Consumo" y "Panel de Becode".
- Voz: `routers/voice.py` (ElevenLabs Agents, modelo de voz `eleven_v4_turbo`),
  `apps/web/src/components/VoiceChat.tsx`, mascota `EchoOrb.tsx`.

**Keys y accesos (nunca commitearlos):**
- Producción: envs de Coolify (`GROQ_API_KEY`, `ELEVENLABS_API_KEY`,
  `ELEVENLABS_AGENT_VOICE_ID`, `OPENAI_API_KEY`...).
- Pruebas: `apps/api/bench/.env` (en `.gitignore`). Si no está, pedírselo a Bauti.
- Coolify (deploy, logs, terminal a la base): token y datos en
  `~/.claude/CLAUDE.md` de la PC. Si no están, pedírselos a Bauti. Nada
  destructivo; no reiniciar ni redeployar sin confirmar.
- **No gastar en APIs para probar** salvo lo mínimo (Groq/ElevenLabs con las
  keys de prueba). Nada de OpenAI para transcribir.

**Cómo probar:**
- API: `docker compose up -d db`, y en `apps/api`
  `DATABASE_URL=postgresql+asyncpg://echo:echo_dev_pw@localhost:5433/echo pytest`
  (necesita `ffmpeg` en el PATH). `ruff check echo_api tests`.
- Web: `pnpm install --frozen-lockfile`, `pnpm build`, `pnpm test`.
- Visual: levantar la web local y mirarla con el navegador integrado (escritorio
  y celular 375×812). Para pantallas logueadas, usar el entorno local con datos
  de prueba (seed), nunca la contraseña de nadie. Mandarle capturas a Bauti de
  los cambios visuales antes de deployar.

**Estado al 1/10 (auditoría de dos agentes):** 211/211 tests del API, ruff
limpio, 14/14 tests web, build de producción ok. Puntajes de código: 8 en
transcripción, personas, seguridad, calidad, migraciones y plan; 7 consumo; 6
planes/créditos/topes; **5 privacidad y menores; 5 agente de voz**. Diseño:
landing 4,5 a 8 (conversión 4,5), app 6 a 7,5. Este plan apunta a **9 o más en
todo**.

---

## 1. Privacidad (primero; nada de esto puede esperar al colegio)

1. **El agente de voz lee reuniones con menores.** `routers/chat.py` filtra las
   reuniones con `meta.minors=true` de los fragmentos y la memoria (≈269-287),
   pero `_structured_block` (≈118-170, llamado ≈300) no recibe el filtro: con
   `voice=true` el LLM (y ElevenLabs) recibe título, decisiones, tareas,
   preguntas, riesgos y resúmenes de reuniones con menores. Pasarle la lista de
   ids sin menores (o `exclude_minors`) y filtrar las cinco consultas. Test que
   reproduce la fuga (reunión con menores → su título y decisión no aparecen en
   el prompt de voz).
2. **El respaldo de transcripción manda audio a OpenAI.**
   `services/ai_settings.py` `stt_fallbacks` (≈166-174) y
   `diarization._text_engine` caen a OpenAI si Groq falla (en vivo, dispositivos,
   pasada final), también con menores. La página legal (`apps/web/src/pages/Legal.tsx`
   ≈137-142) dice que OpenAI "recibe texto, nunca audio". **Sacar OpenAI del
   respaldo de STT** (decisión del plan anterior: OpenAI no transcribe). Si Groq
   cae: reintentar con espera y, si sigue caído, guardar el audio para
   reintentar (ya existe la copia de 48 h) y avisar. Test.
3. **Echo Devices sin "hablan menores".** `routers/device_stream.py`
   (`DeviceMeetingIn` ≈59-60, ≈64-100): agregar el campo y una opción por
   dispositivo; por defecto **activado** en dispositivos (pueden estar en un
   aula). Test: un dispositivo marcado nunca va a ElevenLabs.
4. **Nombres en la pasada con Groq.** Sin Scribe no hay detección de entidades:
   en Gratis y en reuniones con menores, los nombres que no están en la nómina
   le llegan al LLM. Agregar una detección de nombres propios local (heurística
   de mayúsculas a mitad de oración + nómina + participantes; sin mandar audio a
   nadie más) antes de `privacy.protect`. Test con un nombre fuera de nómina.
   Usar también las entidades `phi`/datos que Scribe ya devuelve (hoy solo se
   usan los nombres en `detected_names`).
5. **Voz y nombres.** Con `voice=true`, las respuestas vuelven con los nombres
   reales (`p.restore`) y van a ElevenLabs. Decidir con Bauti: (a) no restaurar
   en voz (decir "la mamá de [ALUMNO_1]" suena mal) o (b) restaurar y
   declararlo en Privacidad. Recomendación: (b) con texto claro, porque la voz
   es del plan individual de un adulto sobre sus propias reuniones; las
   reuniones con menores ya quedan fuera por el punto 1.
6. **"Mi voz" se pide pero no se usa.** `services/diarization.py:99`
   `KNOWN_VOICES_IN_FINAL_PASS = False`. **Decidido por Bauti (1/10): se usa**
   para poner nombres. La implementación está en la **sección 7**. El texto de
   consentimiento y Privacidad tienen que decir para qué se usa, dónde se
   procesa (en el servidor de Echo, no se manda a terceros), cuánto se guarda y
   cómo borrarla.
7. **Legal** (`Legal.tsx`, landing): sumar "Hablar con Echo" (ElevenLabs Agents y
   el LLM que use; solo mayores de 18), "Mi voz" (punto 6), la excepción de 48 h
   de la copia del audio para reintentar, responsable y canal para ejercer
   derechos (Ley 25.326: acceso, rectificación, supresión; "Contact" sin mostrar
   el mail), baja de cuenta, cancelación y responsabilidad en Términos. Nada que
   no se cumpla. Recomendar a Bauti que lo revise un abogado.
8. **Puerta cerrada**: `ElevenLabsProvider.transcribe_chunk`
   (`services/stt/elevenlabs.py` ≈229) no lo usa nadie y permitiría mandar audio
   en vivo a ElevenLabs: borrarlo o que lance error.
9. "Borrar mi voz" borra sin confirmar (`Settings.tsx` ≈1447): pedir confirmación.

---

## 2. Plata: topes que no se esquiven y costos reales

1. **Minutos de voz controlados por el servidor** (`routers/voice.py` ≈84-113,
   ≈220). Hoy el tope del mes lo aplica el reloj del navegador; el servidor solo
   corta cada charla a 600 s; se pueden abrir sesiones en paralelo; y
   `echo_user`/`echo_org` (variables dinámicas) los manda el navegador, así que
   se pueden falsificar y la charla no se anota. Hacer:
   - Registrar en la base cada sesión que se entrega (usuario, organización,
     hora, segundos permitidos = lo que le queda del mes, id de conversación
     cuando llegue).
   - Una sola sesión abierta por usuario; negar otra mientras haya una sin cerrar
     (con vencimiento por si el navegador se cierra).
   - Que el tope de cada charla sea `min(600, lo que queda)` y pasarlo como
     límite de duración del lado de ElevenLabs (override de la conversación),
     no solo en el navegador.
   - Conciliar con la API de conversaciones de ElevenLabs por el id de sesión
     registrado (no por las variables que manda el navegador); lo que no
     concilie, atribuirlo a la última sesión entregada y alertar al superadmin.
   - Tests: sesiones en paralelo, variables falsificadas, tope agotado.
2. **Horas de audio** (`meetings.py` ≈440-442 solo controla en `/start`):
   controlar también en el WebSocket en vivo (`live.py`: al conectar y cada pocos
   minutos; si se pasa, avisar y dejar de transcribir, sin cortar la grabación),
   en importar audio (`imports.py` ≈90-130) y en dispositivos. `month_usage`
   (`plans.py` ≈150-151) solo suma `stt_live`: sumar también `stt_final` de
   importaciones y dispositivos. Tests de cada camino.
3. **Plan Individual sin reserva** (`plans.final_pass_for` ≈300-302): con
   "individual" no hay reserva; dos reuniones a la vez se pasan de las 5 h.
   Reservar horas como se reservan créditos (con el mismo bloqueo por persona).
4. **Créditos que no vuelven** (`diarization.py` ≈403-437, ≈606): si falla algo
   entre la reserva y la pasada, liberar la reserva (`try/except`), e incluir
   reuniones `failed` en el reintento o en una limpieza. Test.
5. **Precios de los modelos.** `plans.py` ≈55-58 solo tiene `gpt-4o-mini` y
   `gpt-4o`: `gpt-6-luna` y `openai/gpt-oss-120b` salen "sin precio" (se ve en
   el Panel de Becode). Cargar el precio de **todos** los modelos que se usan
   (LLM de actas/chat, LLM del agente de voz, embeddings, Groq, Scribe con
   keyterms y entidades, Agents) desde las páginas oficiales de cada proveedor,
   con la fecha y la fuente en un comentario; un test que falle si un modelo
   configurado no tiene precio. Cobrar keyterms solo si hubo vocabulario
   (`diarization.py` ≈563).
6. **"El panel mostraba 0"**: verificar que es por el cambio de mes (el panel
   arranca en el mes actual). Agregar selector de mes visible ("Septiembre /
   Octubre"), comparación con el mes anterior y que el título diga de qué mes son
   los números. `month=9999-12` da 500 (`billing.py` ≈88-91): validar.
7. **Panel de un colegio** (`billing.py` ≈334) muestra a no miembros (el
   superadmin que lo visitó): filtrar por miembros. `admin_billing.py` ≈237-238
   hace una consulta por organización: agrupar.
8. **Agente de voz duplicado** (`voice.ensure_agent` ≈46-58): bloquear para que
   dos sesiones a la vez no creen dos agentes. `main.py` le hace PATCH al agente
   en cada arranque: solo si cambió la configuración.
9. **Margen del plan con voz**: la pantalla dice **60 min** de voz. Costo peor
   caso del plan de US$10: voz 60 × US$0,08 = 4,80 + reuniones 1,30 + LLM ~0,30
   + comisión ~0,80 = ~7,20 → ganancia ~US$2,80 (28%). Con 30 min, ~US$5,20
   (52%). Mostrarle la cuenta a Bauti y que decida (él pidió "un profit
   relativamente lindo").

---

## 3. Landing

Mirarla en el navegador (escritorio 1440, 1024×768, 800×600 y celular 375×812)
antes y después de cada cambio, y mandarle capturas a Bauti.

1. **Intro**: hoy 5-7 s de pantalla negra (video de los ojos,
   `apps/web/src/landing/Hero.tsx`, `/hero/echo-ojos*.mp4`) en cada visita, y en
   1024×768 y 800×600 los ojos tapan el título. Hacer: **un click (o tecla, o
   scroll) en cualquier lado muestra todo al instante**; la intro solo la primera
   vez (sessionStorage/localStorage); `poster` con `echo-ojos-poster.png`;
   respetar `prefers-reduced-motion`; arreglar la superposición en 4:3.
2. **"Ingresar" y "Crear cuenta" arriba a la derecha desde el primer segundo**,
   también durante la intro, bien estéticos (píldoras, "Crear cuenta" sólido,
   "Ingresar" fantasma), fijos al hacer scroll con fondo translúcido.
3. **Sección de precios en la landing**: hoy los planes solo están adentro de la
   app (`Plans.tsx`). Reusar esas tarjetas (Gratis / Individual / Individual +
   voz / Instituciones "Contact sales") en la landing, con anclas en el menú
   (Cómo funciona · Precios · Privacidad) y preguntas frecuentes.
4. **Planes pagos con más valor** (hoy tienen "un poco más" que el gratis).
   Proponerle a Bauti una tabla de diferencias y que elija. Ideas que ya existen
   o son baratas:
   - Gratis: reuniones de hasta 1 h; "Preguntale a Echo" solo sobre cada reunión;
     exportar en PDF.
   - Individual: reuniones largas; quién habló en todas (5 h); "Preguntale a
     Echo" sobre **todas** tus reuniones (memoria); vocabulario propio (nombres
     bien escritos: keyterms de Scribe); exportar DOCX y Documento de Google y
     guardado automático en Drive; importar grabaciones (audio de Zoom/Meet);
     nombres automáticos con "Mi voz" (si se aprueba §1.6); soporte prioritario.
   - Individual + voz: todo lo anterior + conversación por voz + resúmenes
     escuchables.
   - Instituciones: todo + membrete y modelo de acta propio, sedes/niveles,
     panel de consumo por docente, Echo Devices, acompañamiento.
   Comparación tipo ElevenLabs (tarjetas + tabla "comparar planes" debajo).
5. **Copy**: sacar jerga ("motor de voz", "embeddings", "Parakeet, whisper.cpp",
   "API keys", "Echo Bridge", "transcript"; `landing/Steps.tsx`, `Privacy.tsx`,
   `Providers.tsx`). Corregir lo que hoy no es cierto: "Ningún modelo viene
   fijo… cada organización configura su modelo" (ya no es así) y "Echo separa
   hablantes" → **"Echo separa quién habló (en el plan Gratis, 4 reuniones por
   mes)"**. "Reuniones con familias, docentes o clientes": hablar de colegios
   primero.
6. **Demo**: un video corto o capturas de la app andando (el video actual es
   solo la intro de marca). Si hace falta grabar uno, pedirle a Bauti.
7. Footer con "Contact sales" (formulario que avisa a Becode, sin mostrar el
   mail), Privacidad, Términos.
8. Técnica: 2 errores `401 /api/auth/refresh` en la landing pública (no pedir
   refresh sin sesión); `og:image` y títulos por página (vista previa en
   WhatsApp); contraste del gris `ink-400` (#8b94a7, 3,05:1) en textos chicos
   → ≥4,5:1.

---

## 4. App: estética y lo que encontró la auditoría

**Pedidos de Bauti:**
1. **Más border radius y más "clean"**: las cajas/tarjetas más redondeadas (subir
   un escalón: tarjetas `rounded-3xl`, botones e inputs en píldora, como el botón
   "Compartir" pero más redondo), menos bordes duros, más aire. Unificar
   `apps/web/src/components/ui.tsx` (Button/Input `rounded-lg`, Card
   `rounded-xl`) con las pantallas nuevas.
2. **Fuente más redonda/circular**: hoy `index.css:4` declara `"Inter Var"` que
   **nunca se carga** (sale la del sistema) y la landing usa Geist. Probar 2-3
   fuentes redondas geométricas (por ejemplo Nunito, Outfit, Urbanist o
   Quicksand), cargarlas bien (self-host o Google Fonts) en la app **y** la
   landing, y mandarle capturas a Bauti para que elija.
3. **Foto de perfil del login**: guardar la foto de Google al iniciar sesión
   (`routers/auth_google.py`; hoy solo hay `avatar_color` en `models/core.py:28`),
   columna nueva con migración idempotente, refrescarla en cada login y
   mostrarla en el avatar (arriba a la derecha y donde haya avatares), con las
   iniciales de respaldo.

**De la auditoría:**
4. Inicio (`Dashboard.tsx`): skeletons al cargar; "Sin tareas pendientes"
   aparece mientras carga (≈124); clase inexistente `border-ink-150` (≈157);
   estado vacío con botón; mostrar plan y créditos; "primeros pasos".
5. Modales (`ui.tsx` Modal): animación de entrada/salida, foco atrapado y
   devuelto. Pestañas con indicador animado (píldora), `tabpanel` y flechas.
6. Inglés en la interfaz: "Transcript" → "Transcripción"; roles
   "Viewer/Commenter/Editor/Admin" (`MeetingDetail.tsx` ≈28-31) y
   "Member/Admin/Viewer" (`Settings.tsx` ≈170-172); "Usar default del servidor";
   "Markdown (.md)"; "tokens" para no admins. "Preguntar" vs "Preguntale a Echo":
   uno solo.
7. Confirmaciones: "Suscribirme" y "Contact sales" con un paso de confirmación
   (`Plans.tsx` ≈317); "A medida" dice qué incluye.
8. Navegación: la sección "Colegio" (Personas, Familias, Proyectos, Reportes)
   no se muestra en cuentas individuales (`Layout.tsx` ≈155-157); Planes y
   Consumo accesibles desde la barra lateral.
9. Consumo para la persona (`Usage.tsx`): "te quedan X reuniones con quién
   habló / Y h / Z min de voz" con barras; US$ y tokens solo para admins.
   `AnimatedNumber` arranca en el valor final (`billing.tsx` ≈116): que cuente.
10. Crear reunión: línea "lo que protege" (nombres reemplazados antes de la IA,
    audio borrado); avisar que más de 1 h gasta 2 créditos; "Opciones
    avanzadas" plegables; botón "Comenzar" fijo en celular.
11. Onboarding de "Mi voz" (según §1.6): grabar ahí mismo en el aviso,
    escucharla antes de guardar, medidor de nivel; texto que no diga "colegio" a
    los individuales.
12. **Hablar con Echo**: entrada visible (Inicio y barra lateral) para el plan de
    US$10; pantalla previa con los minutos que quedan y "Empezar"; botones de
    silenciar y colgar. Mascota (`EchoOrb.tsx` ≈49-72, ≈205): hoy arma la
    transparencia píxel por píxel en cada cuadro y el bucle nunca para (calienta
    el iPhone) y se ve borrosa en retina (clip de 480 px con `scale-[1.45]`):
    pasar a WebGL/`requestVideoFrameCallback` o video con alfa (HEVC en Safari,
    VP9 en el resto), pausar cuando no se ve, versión 2x.
13. Login: volver al link que se quería abrir (`Login.tsx` ≈35); "Olvidé mi
    contraseña".
14. Celular: botones de 44 px mínimo; probar en 375×812 todas las pantallas.
15. Pasada final con Scribe: no pasar su texto por `HALLUCINATION_SENTENCES` ni
    `collapse_loops` (`diarization._clean_rows` ≈125-133 borra turnos reales
    como "Amén." o "no no no").
16. `pytest.ini` tiene `-q` duplicado.

---

## 5. Orden de trabajo

1. §1 Privacidad completa (con la decisión de Bauti de §1.5).
2. §7 Nombres por voz y "Hablar con Echo" visible (lo que Bauti probó y falló).
3. §2 Plata.
4. §4.1-4.3 (radius, fuente, foto) → capturas a Bauti → elegir fuente.
5. §3 Landing → capturas a Bauti.
6. Resto de §4.
7. Cada bloque: tests verdes, `pnpm build`, capturas, **confirmación de Bauti**
   y deploy (POST a la API de Coolify; verificar que el commit desplegado sea el
   de `main` y que `/api/health` responda).

Al terminar, volver a correr la auditoría: tests, lint, build, revisión de
autorización y menores, y la landing/app en escritorio y celular, con puntaje
por tema. Objetivo: **9 o más en todos**.

## 6. Preguntas para Bauti (hacerlas al llegar a cada punto)

- §1.5: en "Hablar con Echo", ¿nombres reales (declarado en Privacidad) o
  marcadores?
- §7.1: permiso para leer en producción (solo lectura) la última reunión de
  Northfield y las muestras de "Mi voz" de Bauti y su compañero, para
  diagnosticar y calibrar.
- §7.4: ¿activamos "mejorar mi voz con mis reuniones" (opcional, con consentimiento)?
- §7.6: a quien no tiene voz en su plan, ¿le mostramos el globito con "Pasate
  al plan con voz" o no se lo mostramos?
- §7.6: ¿el plan Instituciones incluye voz? (Northfield/Cortesía: sí.)
- §2.9: voz del plan de US$10: ¿60 min (28% de margen en el peor caso) o 30 min
  (52%)?
- §3.4: ¿qué diferencias entre planes elegís?
- §3.6: ¿hay un video de la app o lo grabamos?
- §4.2: ¿qué fuente de las propuestas?

---

## 7. Nombres por voz y "Hablar con Echo" visible (probado por Bauti el 1/10)

**Lo que pasó.** Bauti y un compañero grabaron "Mi voz" antes de empezar, en
Northfield (plan Cortesía). Hablaron ~2 min. La transcripción salió muy bien y
la separación de personas también, pero quedaron como "Persona 1", "Persona 2"
(y alguna etiqueta rara tipo "persona del ambiente") en vez de sus nombres. Y
no encontraron cómo hablarle a Echo por voz.

**Causas (verificadas en el código de `main` 7e5d061):**
- `services/diarization.py:99` `KNOWN_VOICES_IN_FINAL_PASS = False`: las
  muestras de "Mi voz" no se usan. Cuando se usaban, iban *delante del audio*
  que se manda a Scribe (`_known_voices`), y en la reunión del 27/9 eso partió a
  una persona en dos. Ese enfoque no sirve.
- Los nombres hoy solo salen de `name_speakers` (la IA deduce de la
  conversación): sin "soy Fulano" dicho en voz alta, no hay nombre, y puede
  inventar roles raros.
- Voz: el botón es un micrófono chiquito **dentro** de la caja de texto de
  "Preguntale a Echo" (`apps/web/src/components/EchoChat.tsx` ≈163-176), y la
  función `voice` solo se habilita para superadmins o para quien tiene un plan
  individual con voz (`routers/billing.py:136`): el plan de la organización
  (Cortesía/Instituciones) no la da, así que el compañero de Bauti no la ve.

### 7.1 Diagnóstico en producción (pedir permiso a Bauti antes)
Leer (solo lectura, por la terminal de Coolify, contenedor `api`) la última
reunión de Northfield: hablantes (`speakers`: label, display_name,
identity_suggestion), proveedor de la pasada final, si los dos usuarios tienen
`user_voice_samples` y de cuánto, y de dónde salió "persona del ambiente".
Contarle a Bauti lo encontrado. Borrar lo que se deje en `/tmp`.

### 7.2 Poner nombre por huella de voz (después de separar)
- Al guardar "Mi voz": calcular y guardar la **huella** (embedding) de la
  muestra, con un modelo de verificación de hablante en ONNX que corra en CPU
  (WeSpeaker ResNet34 o 3D-Speaker ERes2Net vía `sherpa-onnx`, o ECAPA; en el
  banco WeSpeaker/ERes2Net fueron los mejores). Guardar vector + nombre/versión
  del modelo (pgvector, migración idempotente). Recalcular las existentes con
  un script de una vez.
- Después de la pasada final (Scribe ya separó y trae palabras con tiempo y
  persona): para cada persona, juntar hasta ~30 s de sus tramos limpios (≥1 s,
  sin superposición con otra persona), sacar su huella promedio y compararla
  (coseno) con las de los candidatos: participantes anotados, quien grabó, y
  miembros de la organización con muestra. Asignación uno a uno (algoritmo
  húngaro); se acepta solo si supera un umbral **y** le saca margen al segundo
  mejor; si no, queda como sugerencia (`identity_suggestion`) para confirmar
  con un toque. La persona nombrada queda vinculada al usuario.
- Calibrar umbral y margen con audio real: el banco (`apps/api/bench`) más una
  reunión de prueba de Bauti grabada con "Grabar audio" activado y las muestras
  de los dos (con su permiso). Medir: % de personas bien nombradas, 0 nombres
  equivocados (un nombre mal puesto es peor que "Persona 1").
- CPU: el servidor es chico (2 vCPU). Medir cuánto tarda en una reunión de 1 h;
  si es mucho, limitar segundos por persona. Nada de esto sale a terceros.
- Tests: con huellas falsas (vectores fijos) que la asignación nombre bien, no
  nombre a nadie dos veces y deje sin nombre lo dudoso.

### 7.3 "Hola, soy…"
- Detección determinística en los primeros ~3 minutos: por persona, frases tipo
  "(hola,) soy X", "me llamo X", "habla X", "les habla X"; X se busca en
  participantes, miembros de la organización e integrantes de la familia de la
  reunión. Si coincide uno solo, se pone el nombre con alta confianza. Va antes
  de la huella de voz (si las dos dicen cosas distintas, gana la que dijo la
  persona en voz alta y se marca para revisar).
- En la pantalla de reunión en vivo, al empezar: un consejo amable y
  descartable: "Para que Echo sepa quién es quién, que cada uno diga «Hola, soy…»
  al empezar". También en el modal de nueva reunión, en la línea de qué hace la
  IA.
- `name_speakers` (IA) queda como último recurso: lista cerrada de roles
  (directora, docente, mamá de…, papá de…, etc.), nunca etiquetas inventadas
  como "persona del ambiente"; si no está segura, sin nombre.

### 7.4 Que aprenda (opcional, con consentimiento)
Bauti pidió que si Echo detecta la voz en cualquier reunión la asocie a la
persona. Eso ya pasa con 7.2. Además, opcional y con un interruptor explícito
en "Mi voz" ("Mejorar el reconocimiento con mis reuniones"): cuando una persona
queda confirmada (por coincidencia alta o porque alguien la corrigió a mano a un
usuario que dio ese consentimiento), sumar su huella de esa reunión al perfil
(promedio con tope de muestras). Sin consentimiento, nunca. Es dato biométrico:
contarlo en Privacidad. Preguntarle a Bauti si se activa.

### 7.5 "Mi voz" bien hecha
Grabarla dentro del aviso único y en el registro (sin ir a Ajustes), con
medidor de nivel, escucharla antes de guardar, un texto para leer de ~10 s, y
avisar si quedó muy baja o con ruido. Mostrar en cada reunión qué personas
quedaron nombradas por su voz.

### 7.6 "Hablar con Echo" que se encuentre (el "globito")
- Plan: la función `voice` también la da el plan de la organización cuando lo
  incluye (Cortesía: sí; Instituciones: preguntar a Bauti), no solo el plan
  individual (`routers/billing.py:136` y `routers/voice.py` deben usar la misma
  regla).
- Un **globito flotante** abajo a la derecha (como el widget de ElevenLabs): la
  mascota de Echo animada / ondas de audio, siempre a mano en la app (y en el
  celular, sin tapar botones, respetando las zonas seguras del iPhone). Al
  tocarlo: pantalla previa con los minutos que quedan y "Empezar"; durante la
  charla: ondas que reaccionan a la voz, silenciar y colgar; al terminar,
  minutos usados. Además, una entrada "Hablar con Echo" en la barra lateral y
  una tarjeta en Inicio.
- A quien no tiene voz en su plan: preguntarle a Bauti si el globito aparece
  igual con "Pasate al plan con voz" (a Planes) o no aparece.
- Mascota liviana (ver §4.12: hoy calienta el iPhone y se ve borrosa).
- Probarlo en escritorio y en iPhone (375×812) y mandarle capturas a Bauti.

---

## 8. Estado al terminar (1/10, sesión de implementación)

Todo el plan quedó implementado, con tests (244 del API, 18 web). Decisiones de
Bauti durante la sesión:

| Tema | Decisión |
|---|---|
| §1.5 voz y nombres | Nombres reales en la voz, declarado en Privacidad. |
| Motor de transcripción | Los colegios ya no eligen motor ni cargan keys: Groq con la key de Becode. Ajustes → IA quedó en "Idioma del acta". |
| Baja de cuenta | Botón que pide la baja; Becode la procesa en 5 días hábiles. |
| Responsable | Becode, con formulario de contacto (/contacto), sin mostrar el mail. |
| Cancelación | El plan sigue hasta fin de mes; después pasa a Gratis. |
| §7.4 aprender | Viene prendido al grabar Mi voz; se puede apagar (y se olvida lo aprendido). |
| §7.6 globito | Lo ve todo el mundo; sin voz en el plan, "Pasate al plan con voz". |
| Voz por plan | Solo el plan Individual + voz (y superadmins). Ni Cortesía ni Instituciones: se contrata aparte. bautistagoni@northfield.edu.ar pasó a Individual + voz. |
| §2.9 minutos | 30 min por mes en el plan de US$10 (migración 0021). |
| §3.4 planes pagos | Solo pagos: reuniones de más de 1 h, preguntar sobre todas, Word / Google Docs / Drive, importar grabaciones; soporte prioritario. Aplicado en la app (plans.is_paid). |
| §3.6 demo | Renderizada desde apps/video (EchoDemo) y puesta en la landing. |
| §4.2 fuente | Nunito, servida desde Echo, en la app y la landing. Las actas eligen Arial, Calibri o Times New Roman. |

Lo que no se pudo hacer como decía el plan, y cómo quedó:

- §2.1 "límite de duración del lado de ElevenLabs por override": ElevenLabs no
  deja cambiar `max_duration_seconds` por conversación. Hay un agente por
  duración (1, 3 y 10 min) y cada charla usa el que entra en lo que queda.
- §4.12 mascota 2x: la composición en WebGL y la pausa al no verse están; para
  que se vea nítida en retina hay que volver a exportar los cuatro videos a
  960 px (están en otra PC, "videos/codigo").
- §7.2 calibración: con el banco (3 reuniones) el umbral quedó en 0,75 con
  0,10 de margen. Falta confirmarlo con voces reales: después del deploy,
  `python -m echo_api.voiceprints --comparar` en el contenedor api.

Pendiente de Bauti:

- Configurar el mail (Resend: `RESEND_API_KEY` y `MAIL_FROM`). Mientras
  tanto, "Olvidé mi contraseña" y el contacto llegan a la campanita de Becode.
- Que un abogado revise /legal/privacidad y /legal/terminos.
- Grabar una reunión de prueba con "Hola, soy…" y Mi voz para ver los nombres.
