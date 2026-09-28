Quiero un video demo de producto de ECHO, una aplicación web para colegios. Te adjunto
`echo-demo.mp4`, la versión actual: usala como base de estructura, estilo y ritmo, y
mejorala. No la copies cuadro por cuadro.

## Qué es ECHO
Una app que acompaña las reuniones de un colegio con familias, directivos, el DOE y
profesionales. Se inicia la reunión desde la computadora o el celular y ECHO transcribe
la conversación. Al terminar identifica quién habló y redacta un acta institucional
(motivo, acuerdos y compromisos) que verifica afirmación por afirmación contra lo que se
dijo. La institución revisa el acta y decide. Los compromisos quedan como tareas con
responsable y fecha. Cada reunión se clasifica por familia, motivo y gravedad (verde /
amarillo / rojo) y arma el historial de cada familia. Un asistente ("Preguntale a Echo")
responde qué se acordó en reuniones pasadas, con la fuente.

Idea central: ECHO no es solo un transcriptor. Hace que nadie tenga que tomar notas y
que el equipo vuelva a escuchar y acompañar.

## Formato
- 1920×1080 (16:9), 60 fps, MP4 H.264 de alta calidad (CRF 12–16), audio AAC estéreo.
- Duración: entre 40 y 50 segundos. Nunca más de 50.
- Tiene que entenderse sin voz y también acompañar una narración en vivo (guion abajo).
- Que pueda pasarse en loop: el último frame empalma con el primero.

## Qué tiene que entender alguien que nunca vio ECHO
1. El problema: alguien siempre toma notas en vez de participar. Con ECHO, nadie más.
2. ECHO escucha y transcribe, y sabe quién habló.
3. Sale solo un acta estructurada y verificada contra lo que se dijo.
4. La institución la revisa, la aprueba y la imprime o exporta. La IA no decide.
5. Los compromisos quedan como tareas con responsable y fecha.
6. Todo queda ordenado por familia y gravedad.
7. Se le puede preguntar qué se acordó y responde con la fuente.
8. El audio se guarda solo si la institución lo elige.

## Estructura (como en el video adjunto, con estos tiempos aproximados)
- 0–5 s · Intro con la identidad de ECHO: pantalla negra, sube la luz y aparecen los dos
  ojos de ECHO (dos píldoras negras), que pestañean. Es el hero de la landing y está al
  principio del video adjunto.
- 5–8 s · Problema: una libreta con notas escritas apuradas. Copy: "Alguien siempre toma
  notas." Enseguida cada renglón se tacha y aparece "Con Echo, nadie más."
- 8–15 s · La libreta se transforma en "Nueva reunión" (Familia Romero). "Iniciar reunión".
  "Grabando", timer, líneas del transcript en vivo (primero en gris, después
  definitivas). "⭐ Momento". "Finalizar". Antes de iniciar, el cursor pasa por
  "Grabar el audio completo" y lo deja sin tildar. Copy: "Vos escuchás. Echo anota."
- 15–17 s · Procesando, una etapa por golpe: "Identificando quién habló…", "Extrayendo
  decisiones y tareas…", "Generando el acta…". Copy: "Guardar el audio: opcional."
- 17–22 s · Transcript con los hablantes en color (Directora, Mamá de Pedro, Orientadora
  (DOE)). Clasificar: gravedad Amarillo, asistencia tutor por tutor, Guardar. El
  resultado queda en chips.
- 22–31 s · Momento clave, el acta: afirmaciones verificadas ✓ ✓ ⚠ con su minuto (00:13).
  El acta completa se tiene que poder LEER (Motivo / Acuerdos / Compromisos). Después
  "Enviar a revisión" → "Aprobar" (el estado cambia al lado del botón) e "Imprimir", que
  abre la hoja formal con membrete, firmas y "Acta aprobada · versión 1 · Generada con
  Echo". Copy: "Acta verificada." → "La institución decide."
- 31–34 s · Tareas: "Coordinar reunión con la psicopedagoga · Directora · 2026-10-02".
  Copy: "Tareas con fecha."
- 34–39 s · "Preguntale a Echo": se escribe letra por letra "¿Qué acordamos con la familia
  Romero?". Llega la respuesta con sus fuentes. Click en la fuente y se abre el
  fragmento del transcript resaltado. Copy: "Echo recuerda."
- 39–42 s · Historial de la familia con el semáforo. Copy: "Todo en orden."
- 42–45 s · Cierre: el ícono de ECHO (cuadrado negro redondeado con dos ojos blancos),
  "Echo" y "La reunión termina. Echo recuerda." Vuelve al negro del primer frame.

## Lo que falló en versiones anteriores (no repetirlo)
- Texto que no se llega a leer. Todo lo que importa (el acta, las tareas, la respuesta)
  queda en pantalla al menos 2 s y a un tamaño legible: hacé zoom si hace falta.
- Clicks que "no hacen nada". Cada click produce un cambio visible cerca del cursor. Si
  el cambio real ocurre lejos, la cámara muestra el botón y el resultado juntos. No
  hagas clicks en botones que solo descargan un archivo.
- Mensaje ambiguo al principio. Tiene que quedar claro que la idea es dejar de tomar
  notas, no que alguien las toma.
- Promesas falsas. No digas "el audio nunca se guarda": guardarlo es una opción.

## Dirección visual
- Demo de software premium (nivel Product Hunt o landing de startup). No una grabación
  de pantalla ni un template.
- Usá la UI real de ECHO (fondo #fafbfc, tinta #0c0e16/#141824, acento índigo #4f46e5,
  tipografía Geist, bordes suaves y cards blancas), tal como se ve en el video adjunto.
  Podés simplificar una pantalla para que se lea, sin cambiarle la identidad.
- Una sola superficie que se transforma (libreta → modal → app → hoja → ícono), sin cortes
  duros. Springs suaves, blur cortísimo solo durante los cruces, nada de rebotes,
  partículas, glows ni transiciones tipo PowerPoint.
- Cámara narrativa: zoom al elemento relevante y vuelta al contexto. Nunca zoom mientras
  cambia un texto.
- Cursor protagonista: flecha estándar, curvas naturales, click con el botón que se hunde
  y un anillo chico, escritura letra por letra, pausas justas.
- Copy arriba de la UI, de 1 a 4 palabras y en dos tonos (una parte en índigo), que entra
  palabra por palabra.

## Audio
- Música de fondo a 120 BPM. Los clicks y los cambios importantes caen en los golpes. La
  música entra con la luz del intro y termina con el video.
- Efectos sutiles: click de mouse en cada click, teclas al escribir, un tic por
  afirmación verificada y un soplo suave en las transformaciones grandes.

## Datos (ficticios, nunca reales)
Colegio San Martín, Familia Romero (legajo 1482), alumno Pedro, "Mamá de Pedro" (Laura
Romero), "Directora", "Orientadora (DOE)", motivo "Seguimiento de convivencia", gravedad
Amarillo, acuerdo "Reunión con la psicopedagoga el viernes 2 de octubre", reunión del
28 sept.

## Lo que ECHO hace y no hace (no inventar)
- Exporta el acta a PDF, DOCX y MD, y la imprime con membrete y firmas.
- Acta: Editar, Regenerar, Enviar a revisión → Aprobar (Borrador → En revisión →
  Aprobada), con historial de versiones. NO existe "pedirle cambios a la IA".
- La verificación muestra ✓ / ⚠ / ✗ con el minuto, sin cita textual.
- Los hablantes con nombre aparecen al finalizar (en vivo no se separan).
- "Grabar el audio completo" es opcional y viene apagado. Si se activa, el audio va al
  Drive de quien grabó o se descarga durante 48 h.
- Las agendas, recordatorios o integraciones que no ves en el video: no existen, no los
  muestres.

## Guion para narrar encima (debe calzar con los tiempos)
0:00 En un colegio, las reuniones con familias, directivos y el DOE son constantes.
0:05 Y casi siempre alguien termina tomando notas en vez de participar. Con Echo, nadie más.
0:09 Se inicia desde la compu o el celular: mientras el equipo conversa, Echo escucha y transcribe.
0:15 El audio se guarda solo si la institución lo elige.
0:17 Al terminar, sabe quién habló, y la reunión queda ordenada por familia y gravedad.
0:22 Echo redacta el acta con motivo, acuerdos y compromisos, y verifica cada afirmación contra lo que se dijo.
0:26 La institución la revisa, la aprueba y la imprime o la exporta.
0:31 Los compromisos quedan como tareas, con responsable y fecha.
0:34 Y para recordar qué se acordó, se le pregunta a Echo: responde y muestra de dónde lo sacó.
0:39 Todo queda en el historial de cada familia.
0:42 El equipo vuelve a lo importante: escuchar y acompañar. La reunión termina. Echo recuerda.

## Proceso y entregables
1. Mirá el video adjunto y escribí un storyboard con cada momento (tiempo, qué se ve,
   cursor, cámara, copy) antes de producir.
2. Producí el video.
3. QA antes de entregar: revisá un cuadro por momento y comprobá que todo se lee, que
   ningún click queda sin resultado visible, que nada se superpone, que no hay cuadros
   muertos ni texto borroso y que no supera los 50 s.
4. Entregá el MP4, el storyboard y los cuadros de QA.
