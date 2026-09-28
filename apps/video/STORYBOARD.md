# Echo — demo de producto (30 s)

**Concepto.** Una reunión con la familia Romero, de punta a punta, sobre una
sola superficie que se transforma: Echo escucha, redacta el acta, la verifica,
la institución la aprueba, y meses después Echo la recuerda con la fuente.
Nadie tuvo que tomar notas.

- 1920×1080, 60 fps, 1800 frames (30,0 s). Composición `EchoDemo`.
- Música: `public/music.mp3` (la pista del video de Testra, para que los tres
  videos de BeCode suenen igual). Medida: **120 BPM exactos, primer golpe en
  el frame 17**. Grilla: `beat(n) = 17 + 30·n`. Los clicks y los cambios de
  estado caen en golpes.
- Lenguaje heredado del video de Testra (`reference/`): fondo claro de la app,
  copy de dos tonos que entra palabra por palabra con un blur corto, UI real
  grande y legible, flecha de cursor estándar, cierre con logo + tagline sobre
  el mismo fondo.

## Qué se verificó en el código (y cómo cambió la historia)

| Pedido original | En el código | En el video |
|---|---|---|
| Ficha de familia con semáforo y "+ Nueva reunión" | La tarjeta de familia no tiene semáforo; el historial con semáforo está en el panel **Reuniones de la familia** (`FamilyMeetingsPanel`). "+ Nueva reunión" abre un modal con campo **Familia** (`Meetings.tsx`) | Se abre el modal **Nueva reunión** con la Familia Romero; el historial con semáforo va al cierre |
| Pill "El audio no se guarda" en vivo | No existe en la app. La frase es de la landing (`landing/Privacy.tsx`); en la app, "Grabar el audio completo" está apagado por defecto | Copy "El audio no se guarda." al finalizar (cuando el audio se descarta), y el checkbox real apagado en la pantalla previa |
| Chips de hablante de colores en vivo | En vivo el hablante es texto gris y con un micrófono no hay separación; los nombres con color salen al finalizar ("Identificando quién habló…") en la tab Transcript | Vivo sin hablantes; Transcript con "Quién habló (tocá para corregir):" y nombres de color |
| Etapas que se tildan | La pantalla muestra una etapa a la vez con barra de progreso | Una etapa por golpe, con la barra |
| Quién solicitó la reunión | No está en la clasificación (solo en la plantilla de entrevista) | No se muestra |
| Evidencia con cita textual `[00:13]` | La verificación lista cada afirmación con ✓ / ⚠ / ✗ y el tiempo `00:13` (sin cita) y aparece cuando alguna necesita revisión | Lista real: tres ✓ y un ⚠, con sus tiempos |
| "Exportar → PDF" | No hay menú "Exportar": botones **PDF**, **DOCX**, **MD** e **Imprimir** | Click en **PDF** |
| Editar / regenerar / enviar a revisión / pedirle cambios a la IA | Existen **Editar**, **Regenerar**, **Enviar a revisión → Aprobar** (Borrador → En revisión → Aprobada). No existe "pedirle cambios a la IA" | Enviar a revisión → Aprobar |
| Tarea "vie 2 oct" | La tab Tareas muestra la fecha ISO (`2026-10-02`) | `2026-10-02` (reunión del lunes 28/9: "el viernes" = 2/10) |
| Fuente como chip | En Preguntale a Echo, las fuentes son links «Título» — MM:SS · hablante, y llevan a la reunión con el fragmento resaltado | Link real y salto al transcript resaltado |
| Secciones Motivo / Acuerdos / Compromisos | El acta sigue la plantilla que carga cada institución (Ajustes → Formato de acta) | Plantilla de ejemplo con esas secciones |
| Fuente Geist | La landing usa Geist; la app declara "Inter Var" sin cargarla | Geist, como la landing |

## Grilla

`B(n)` = frame del golpe n. Superficie = la única forma que se transforma.

| # | Tiempo | Frames | Superficie / UI | Cursor | Cámara | Copy |
|---|---|---|---|---|---|---|
| 1 | 0,00–2,78 s | 0–167 | Bloque de notas: se escribe apurado ("Reunión flia. Romero", "psicopedag… ¿viernes?"), una línea tachada | — | quieta | B0 "Alguien siempre" · B1 "**toma notas.**" |
| 2 | 2,78–4,28 s | 167–257 | B5: la libreta se estira y se vuelve el modal **Nueva reunión** (Familia Romero · Familia y profesionales · participantes) | entra B5, click **Comenzar reunión** en B7 | quieta | — |
| 3 | 4,28–9,28 s | 257–557 | B8: el modal crece a la app (barra lateral + **Todo listo para empezar**, "Grabar el audio completo" apagado). B10 click **Iniciar reunión** → header con cara roja, **Grabando**, timer. Líneas: parcial gris → definitiva (B11/B12, B12/B13, B14/B15 "Acordamos una reunión con la psicopedagoga el viernes."). Panel "Echo está detectando" suma una decisión y una tarea | B10 Iniciar; B16 **⭐ Momento**; B18 **Finalizar** | B10.4 zoom al transcript (×1,5); B15.2 vuelve | B10 "**Echo** escucha." |
| 4 | 9,28–11,28 s | 557–677 | B18: el contenido se vuelve la pantalla de proceso: cara pensando, **Identificando quién habló…** (B19), **Extrayendo decisiones y tareas…** (B20), **Generando el acta…** (B21), barra | reposa | quieta | B19 "El audio **no se guarda.**" |
| 5 | 11,28–12,78 s | 677–767 | B22: la reunión: título, "Primaria", meta, **Esta reunión no está clasificada.**, tabs; Transcript con **Quién habló (tocá para corregir):** Directora · Mamá de Pedro · Orientadora (DOE) | se acerca a "Clasificar" | B23 zoom a hablantes; B25 vuelve | B22 "Sabe **quién habló.**" |
| 6 | 12,78–15,28 s | 767–917 | B26 **Clasificar** → el panel se despliega (¿Con quién fue?, Familia, Motivo "Seguimiento de convivencia", Gravedad, ¿Quiénes vinieron?). B27 **Amarillo**. B28 ✓ Laura Romero (madre). B29 **Guardar** → chips: Familia Romero · Familia y profesionales · Seguimiento de convivencia · Amarillo · Faltó alguno | los cuatro clicks | leve zoom al panel | B26 "Por familia **y gravedad.**" |
| 7 | 15,28–19,78 s | 917–1187 | **AHA.** B30 tab **Acta**: "Acta N.º 14", **Borrador**, "v1 · Generada automáticamente", Imprimir · Editar · Enviar a revisión · Regenerar · PDF · DOCX · MD; "El acta ya está lista. Echo sigue verificando…". Verificación: ✓ B31, ✓ B32 (psicopedagoga · 00:13), ⚠ B33. B34 la página scrollea al acta entera: Motivo / Acuerdos / Compromisos. B36 **Enviar a revisión** → En revisión; B37 **Aprobar** → Aprobada; B38 **PDF** | B32 se posa en la afirmación de 00:13 | B30.3 zoom a la verificación (×1,7); B34 vuelve | B30.4 "Acta **verificada.**" · B35.5 "La institución **decide.**" |
| 8 | 19,78–21,28 s | 1187–1277 | B39 tab **Tareas**: "Coordinar reunión con la psicopedagoga · Directora · 2026-10-02 · Pendiente" | click en la tab | B40 zoom a la fila | B39 "Tareas **con fecha.**" |
| 9 | 21,28–25,28 s | 1277–1517 | B42 **Preguntale a Echo** (barra lateral). Se escribe "¿Qué acordamos con la familia Romero?" letra por letra; B45 **Enviar**; "Buscando en la memoria de reuniones…"; B46 respuesta con **FUENTES** «Familia Romero · 28 sept» — 00:13 · Orientadora (DOE). B48 click → la reunión con el fragmento de 00:13 resaltado | escribe, envía, toca la fuente | B49 paneo al fragmento resaltado | B43 "**Echo** recuerda." |
| 10 | 25,28–27,28 s | 1517–1637 | B50 **Familias** → B51 **Reuniones** → panel **Reuniones de la familia**: 4 reuniones, barra verde/amarillo/rojo, filas con su color | dos clicks | quieta | B51 "Todo **en orden.**" |
| 11 | 27,28–30,00 s | 1637–1800 | B54 la app se encoge al ícono de Echo (cuadrado negro con dos ojos, el favicon); B55 "Echo" y "La reunión termina. Echo recuerda."; B58 el ícono se vuelve la libreta vacía del frame 0 (loop) | sale | quieta | tagline |

## Aha moment

B31–B33: sobre la verificación, las afirmaciones del acta se van tildando
contra el transcript, una por golpe, con su minuto. La que no está clara queda
en ⚠: la IA no decide por la institución. Dos golpes después la institución
la envía a revisión y la aprueba.

## Reglas de movimiento

- Una sola superficie (`Surface`): rectángulo, radio y color interpolados con
  `spring` (damping alto, sin rebote). El contenido cambia con un blur de
  ≤ 6 px durante ≤ 12 frames; ningún texto queda borroso fuera de ese cruce.
- La cámara solo se mueve cuando el texto está quieto; los cambios de texto
  caen en golpes con la cámara ya asentada.
- Cursor: curvas con un leve arco, llegada con ease-out, click = el botón se
  hunde (scale 0,97) y un anillo chico de 18 px que se desvanece en 14 frames.
- Cada estado queda al menos ~0,5–0,6 s en pantalla.
- Sin `will-change`: el texto se re-rasteriza en cada escala y queda nítido.

## Archivos y cómo se renderiza

- `src/demo/timeline.ts`: la grilla (`B(n)`), los actos, los clicks, las líneas del vivo y el copy.
- `src/demo/camera.tsx`: la superficie única (`Surface`), la cámara (`cameraAt`, acotada a la app) y `toScreen` para el cursor.
- `src/demo/Cursor.tsx`: los objetivos del cursor; cada click llega en su golpe.
- `src/demo/layout.ts`: coordenadas compartidas por la UI y el cursor.
- `src/demo/scenes/*`: libreta, modal, vivo, proceso, reunión (transcript, clasificación, acta, tareas), Preguntale a Echo, familias, logo.
- `src/demo/ui/*` y `../web/src/components/ui.tsx`: la UI. `Button`, `Badge` y `Card` se importan de la app real.

```bash
cd apps/video && npm install
npm run stills:demo            # QA: un still por golpe en out/stills/
npx remotion render src/index.ts EchoDemo out/echo-demo.mp4 --codec=h264 --crf=12
# en un contenedor sin Chrome de Remotion: --browser-executable=<chromium headless>
```
