import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

const INK = "#0c0e16";
const PAPER = "#fafbfc";

/**
 * Todo negro. Se enciende una luz en el centro que crece con un borde muy
 * difuso hasta que la pantalla queda toda blanca; los ojos, que estaban ahí
 * desde el primer frame, quedan negros. Después pestañean dos veces.
 */
export const EchoOjos = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const at = (seconds: number) => seconds * fps;

  // Negro 0.5 s; la luz crece de 0.5 s a 1.8 s y se queda.
  const t = interpolate(frame, [at(0.5), at(1.8)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  // Radio del halo en % de la distancia al vértice; el borde se difumina
  // `feather` a cada lado, así nunca se ve un círculo, solo luz que sube.
  const feather = 60;
  const radius = -feather + t * (100 + 2 * feather);
  const background =
    t <= 0
      ? INK
      : t >= 1
        ? PAPER
        : `radial-gradient(circle at 50% 50%, ${PAPER} ${radius - feather}%, ${INK} ${radius + feather}%)`;

  // Un pestañeo: cierra en 80 ms, abre en 120 ms.
  const blink = (start: number) =>
    interpolate(frame, [at(start), at(start + 0.08), at(start + 0.2)], [1, 0.06, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.quad),
    });
  const scaleY = Math.min(blink(2.2), blink(2.6));

  const eye = { width: 150, height: 225, borderRadius: 999, background: INK, transform: `scaleY(${scaleY})` };

  return (
    <AbsoluteFill style={{ background, justifyContent: "center", alignItems: "center" }}>
      <div style={{ display: "flex", gap: 112 }}>
        <div style={eye} />
        <div style={eye} />
      </div>
    </AbsoluteFill>
  );
};
