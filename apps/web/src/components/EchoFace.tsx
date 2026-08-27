/**
 * La cara de Echo: dos ojos minimalistas. La misma identidad vive en la web,
 * el favicon y el dispositivo ESP32.
 *
 * Estados: idle (espera), listening (escucha, reacciona al volumen),
 * thinking (procesa), sleeping (pausa), done (sonríe), error.
 */

export type EchoMood = "idle" | "listening" | "thinking" | "sleeping" | "done" | "error";

export function EchoFace({
  mood = "idle",
  size = 48,
  level = 0,
}: {
  mood?: EchoMood;
  size?: number;
  level?: number; // 0..1 nivel de audio en modo listening
}) {
  const eyeHeight = mood === "sleeping" ? 2 : mood === "listening" ? 10 + Math.min(6, level * 14) : 12;
  const eyeY = 20 - eyeHeight / 2;
  const stroke = mood === "error" ? "#ef4444" : "currentColor";

  return (
    <svg
      viewBox="0 0 40 40"
      width={size}
      height={size}
      className={
        "select-none " +
        (mood === "listening" ? "echo-listening " : "") +
        (mood === "thinking" ? "echo-thinking" : "")
      }
      aria-label={`Echo ${mood}`}
      role="img"
    >
      <g className="echo-pupils">
        {mood === "done" ? (
          <>
            <path d="M10 18 q3.5 -5 7 0" fill="none" stroke={stroke} strokeWidth={3} strokeLinecap="round" />
            <path d="M23 18 q3.5 -5 7 0" fill="none" stroke={stroke} strokeWidth={3} strokeLinecap="round" />
            <path d="M13 27 q7 6 14 0" fill="none" stroke={stroke} strokeWidth={2.5} strokeLinecap="round" />
          </>
        ) : mood === "error" ? (
          <>
            <line x1={10} y1={14} x2={17} y2={21} stroke={stroke} strokeWidth={3} strokeLinecap="round" />
            <line x1={17} y1={14} x2={10} y2={21} stroke={stroke} strokeWidth={3} strokeLinecap="round" />
            <line x1={23} y1={14} x2={30} y2={21} stroke={stroke} strokeWidth={3} strokeLinecap="round" />
            <line x1={30} y1={14} x2={23} y2={21} stroke={stroke} strokeWidth={3} strokeLinecap="round" />
            <line x1={14} y1={28} x2={26} y2={28} stroke={stroke} strokeWidth={2.5} strokeLinecap="round" />
          </>
        ) : (
          <>
            <rect className="echo-eye" x={9} y={eyeY} width={8} height={eyeHeight} rx={4} fill={stroke} />
            <rect className="echo-eye" x={23} y={eyeY} width={8} height={eyeHeight} rx={4} fill={stroke} />
            {mood === "thinking" && (
              <g fill={stroke} opacity={0.6}>
                <circle cx={14} cy={31} r={1.6} />
                <circle cx={20} cy={31} r={1.6} />
                <circle cx={26} cy={31} r={1.6} />
              </g>
            )}
          </>
        )}
      </g>
    </svg>
  );
}
