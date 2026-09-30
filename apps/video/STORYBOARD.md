# Echo — demo de producto (30 s)

> Los tiempos de la grilla son de la demo (frame 0 = la libreta); en el video
> final van corridos 5,5 s por el intro.

**Concepto.** Una reunión con la familia Romero, de punta a punta, sobre una
sola superficie que se transforma: Echo escucha, redacta el acta, la verifica,
la institución la aprueba, y meses después Echo la recuerda con la fuente.
Nadie tuvo que tomar notas.

- 1920×1080, 60 fps, 2730 frames (45,5 s). Composición `EchoDemo`: primero el
  hero de la landing y después 40 s de demo.
- **Intro (0–5,5 s):** el video con el que abre la landing (`Variantes.tsx`,
  variante "lee", el mismo que `apps/web/public/hero/echo-ojos.mp4`), renderizado
  acá a 60 fps: negro, sube la luz, los ojos leen dos renglones, te miran y
  pestañean. A los 5,5 s los ojos se achican y se van mientras entra la libreta.
  La demo arranca en el frame 330 = 11 golpes: la grilla no se corre.
- Música: `public/music.mp3`, la pista del video de Testra
  (`public/music-testra.mp3`, para que los tres videos de BeCode suenen igual)
  extendida a 44 s con `scripts/music.py`: repite cinco compases con los cortes
  en golpe, así la grilla no se corre. Entra a los 1,5 s, cuando sube la luz, y
  termina con el video: su final natural.
- Efectos (`public/sfx`, sintetizados con `scripts/sfx.py`, `src/demo/Sound.tsx`):
  click de mouse en cada click, una tecla por letra al escribir, un tic por
  afirmación verificada y un soplo suave en cada transformación de la
  superficie. Cada uno en el frame exacto de lo que se ve. Medida: **120 BPM exactos, primer golpe en
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
| Pill "El audio no se guarda" en vivo | No existe en la app, y como absoluto no es cierto: "Grabar el audio completo" es una opción (apagada por defecto; si se activa, el audio va al Drive de quien grabó o se descarga durante 48 h) | Antes de iniciar, el cursor pasa por "Grabar el audio completo" y lo deja sin tildar; al finalizar, el copy "Guardar el audio: **opcional.**" |
| Chips de hablante de colores en vivo | En vivo el hablante es texto gris y con un micrófono no hay separación; los nombres con color salen al finalizar ("Identificando quién habló…") en la tab Transcript | Vivo sin hablantes; Transcript con "Quién habló (tocá para corregir):" y nombres de color |
| Etapas que se tildan | La pantalla muestra una etapa a la vez con barra de progreso | Una etapa por golpe, con la barra |
| Quién solicitó la reunión | No está en la clasificación (solo en la plantilla de entrevista) | No se muestra |
| Evidencia con cita textual `[00:13]` | La verificación lista cada afirmación con ✓ / ⚠ / ✗ y el tiempo `00:13` (sin cita) y aparece cuando alguna necesita revisión | Lista real: tres ✓ y un ⚠, con sus tiempos |
| "Exportar → PDF" | No hay menú "Exportar": botones **PDF**, **DOCX**, **MD** e **Imprimir**. PDF/DOCX/MD descargan un archivo (en pantalla no pasa nada); Imprimir abre la hoja del acta | Click en **Imprimir** → la hoja con firmas y "Acta aprobada"; los botones de exportación quedan a la vista |
| Editar / regenerar / enviar a revisión / pedirle cambios a la IA | Existen **Editar**, **Regenerar**, **Enviar a revisión → Aprobar** (Borrador → En revisión → Aprobada). No existe "pedirle cambios a la IA" | Enviar a revisión → Aprobar |
| Tarea "vie 2 oct" | La tab Tareas muestra la fecha ISO (`2026-10-02`) | `2026-10-02` (reunión del lunes 28/9: "el viernes" = 2/10) |
| Fuente como chip | En Preguntale a Echo, las fuentes son links «Título» — MM:SS · hablante, y llevan a la reunión con el fragmento resaltado | Link real y salto al transcript resaltado |
| Secciones Motivo / Acuerdos / Compromisos | El acta sigue la plantilla que carga cada institución (Ajustes → Formato de acta) | Plantilla de ejemplo con esas secciones |
| Fuente Geist | La landing usa Geist; la app declara "Inter Var" sin cargarla | Geist, como la landing |

## Grilla

`B(n)` = frame del golpe n de la demo (en el video: + 5,5 s). Superficie = la
única forma que se transforma.

| # | Video | Golpes | Superficie / UI | Cursor | Cámara | Copy |
|---|---|---|---|---|---|---|
| 0 | 0,0–5,5 s | — | Hero de la landing ("lee"): negro, sube la luz, los ojos leen, miran y pestañean | — | — | — |
| 1 | 5,5–8,3 s | B0–B5 | Libreta: alguien escribe apurado; B3.4 cada renglón se tacha | — | quieta | "Alguien siempre **toma notas.**" → "Con Echo, **nadie más.**" |
| 2 | 8,3–9,8 s | B5–B8 | La libreta se vuelve el modal **Nueva reunión** (Familia Romero, Familia y profesionales, participantes, "Grabar el audio completo" sin tildar) | click **Comenzar reunión** B7 | quieta | — |
| 3 | 9,8–14,8 s | B8–B18 | **Todo listo para empezar**; B9 el cursor pasa por "Grabar el audio completo" y lo deja; B10 **Iniciar reunión** → Grabando, timer, líneas parcial → definitiva, "Echo está detectando" | B10, B16 **⭐ Momento**, B18 **Finalizar** | B10.4 zoom al transcript; B15.2 vuelve | "Vos escuchás. **Echo anota.**" |
| 4 | 14,8–16,8 s | B18–B22 | Proceso: Identificando quién habló… → Extrayendo decisiones y tareas… → Generando el acta… | reposa | quieta | "Guardar el audio: **opcional.**" |
| 5 | 16,8–19,3 s | B22–B27 | Transcript con **Quién habló (tocá para corregir):** Directora · Mamá de Pedro · Orientadora (DOE) | — | B22.8 zoom a hablantes; B25.5 vuelve | "Sabe **quién habló.**" |
| 6 | 19,3–21,8 s | B27–B32 | **Clasificar** → Amarillo → ✓ Laura Romero (madre) → **Guardar** → chips: Familia Romero · Familia y profesionales · Seguimiento de convivencia · Amarillo · Faltó alguno | B27, B28, B29, B30 | quieta | "Por familia **y gravedad.**" |
| 7 | 21,8–28,3 s | B32–B45 | **AHA.** Tab **Acta**; verificación ✓ B33, ✓ B34 (00:13), ⚠ B35; B36.3 la página scrollea y se lee el acta entera (Motivo, Acuerdos, Compromisos); **Enviar a revisión** B41 → En revisión; **Aprobar** B43 → Aprobada | B32 tab, B34 sobre la afirmación de 00:13, B41, B43 | B32.3 verificación (×1,7); B36.8 el acta (×1,45); B40.3 la barra con el estado (×1,55) | "Acta **verificada.**" → "La institución **decide.**" |
| 8 | 28,3–30,8 s | B45–B50 | **Imprimir** → la hoja del acta (membrete, título, acta, firmas, "Acta aprobada · versión 1 · Generada con Echo"); B50 **Volver a la reunión** | B45, B50 | B45.4 la hoja arriba; B47.2 firmas y pie | "La institución **decide.**" |
| 9 | 30,8–33,3 s | B51–B56 | Tab **Tareas**: Coordinar reunión con la psicopedagoga · Directora · 2026-10-02; Seguimiento con la familia Romero · Orientadora (DOE) · 2026-10-09 | B51 tab, B53 sobre la fecha | B51.3 zoom a la tabla (×1,5) | "Tareas **con fecha.**" |
| 10 | 33,3–38,3 s | B56–B66 | **Preguntale a Echo**: se escribe "¿Qué acordamos con la familia Romero?", **Enviar**, la respuesta con **FUENTES**; B64 la fuente → el fragmento de 00:13 resaltado | B56, B57, B59, B64 | B60.3 la respuesta; B64.3 el fragmento | "**Echo** recuerda." |
| 11 | 38,3–41,8 s | B66–B73 | **Familias** → **Reuniones** → panel **Reuniones de la familia** (4 reuniones, barra verde/amarillo/rojo, filas con su color) | B66, B67 | B67.8 zoom al panel | "Todo **en orden.**" |
| 12 | 41,8–45,5 s | B73–B80 | La app se encoge al ícono de Echo; "Echo" y "La reunión termina. Echo recuerda."; B78 el ícono crece hasta el negro del primer frame (loop) | sale | quieta | tagline |

## Aha moment

B33–B35: sobre la verificación, las afirmaciones del acta se van tildando
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
