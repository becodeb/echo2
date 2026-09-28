import { interpolate } from "remotion";

/**
 * La cara de Echo con la geometría exacta de apps/web/src/components/EchoFace
 * (viewBox 40×40, ojos de 8×12 con rx 4). En la web el pestañeo es una
 * animación CSS; acá se deriva del frame para que el render sea determinista.
 */
export function Face({
  mood = "idle",
  size = 48,
  frame,
  blinkAt = [],
  level = 0,
  color = "currentColor",
}: {
  mood?: "idle" | "listening" | "thinking" | "done";
  size?: number;
  frame: number;
  blinkAt?: number[];
  level?: number;
  color?: string;
}) {
  const blink = blinkAt.reduce((scale, at) => {
    const d = frame - at;
    if (d < 0 || d > 12) return scale;
    return Math.min(scale, interpolate(d, [0, 4, 12], [1, 0.08, 1]));
  }, 1);
  const eyeHeight = mood === "listening" ? 10 + Math.min(6, level * 14) : 12;
  const eyeY = 20 - eyeHeight / 2;
  // "thinking": las pupilas van y vienen 3 px (echo-think, 1,2 s).
  const think = mood === "thinking" ? Math.sin((frame / 72) * Math.PI * 2) * 3 : 0;

  if (mood === "done") {
    return (
      <svg viewBox="0 0 40 40" width={size} height={size} aria-hidden>
        <path d="M10 18 q3.5 -5 7 0" fill="none" stroke={color} strokeWidth={3} strokeLinecap="round" />
        <path d="M23 18 q3.5 -5 7 0" fill="none" stroke={color} strokeWidth={3} strokeLinecap="round" />
        <path d="M13 27 q7 6 14 0" fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 40 40" width={size} height={size} aria-hidden>
      <g transform={`translate(${think} 0)`}>
        {[9, 23].map((x) => (
          <rect
            key={x}
            x={x}
            y={eyeY}
            width={8}
            height={eyeHeight}
            rx={4}
            fill={color}
            style={{ transformBox: "fill-box", transformOrigin: "center", transform: `scaleY(${blink})` }}
          />
        ))}
        {mood === "thinking" && (
          <g fill={color} opacity={0.6}>
            <circle cx={14} cy={31} r={1.6} />
            <circle cx={20} cy={31} r={1.6} />
            <circle cx={26} cy={31} r={1.6} />
          </g>
        )}
      </g>
    </svg>
  );
}
