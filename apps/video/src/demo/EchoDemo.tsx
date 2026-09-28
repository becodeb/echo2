import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./demo.css";
import { useEffect, useState } from "react";
import { AbsoluteFill, Audio, continueRender, delayRender, interpolate, staticFile, useCurrentFrame } from "remotion";
import { presence } from "./anim";
import { AppViewport, Fill, NOTES_VIRTUAL, Surface } from "./camera";
import { Captions } from "./Caption";
import { Cursor } from "./Cursor";
import { APP_H, APP_W, MODAL_H, MODAL_W } from "./layout";
import { Ask } from "./scenes/Ask";
import { Detail } from "./scenes/Detail";
import { Families } from "./scenes/Families";
import { Live } from "./scenes/Live";
import { LogoLockup } from "./scenes/Logo";
import { NewMeeting } from "./scenes/NewMeeting";
import { Notes } from "./scenes/Notes";
import { Processing } from "./scenes/Processing";
import { ACT, B, CLICK, DURATION } from "./timeline";
import { Face } from "./ui/Face";
import { Sidebar } from "./ui/Sidebar";

/** Espera a que Geist esté cargada antes de sacar el primer frame. */
function useFonts() {
  const [handle] = useState(() => delayRender("Geist"));
  useEffect(() => {
    Promise.all([
      document.fonts.load('400 16px "Geist Variable"'),
      document.fonts.load('600 16px "Geist Variable"'),
      document.fonts.load('400 16px "Geist Mono Variable"'),
    ]).then(() => continueRender(handle));
  }, [handle]);
}

/** Qué pantalla ocupa el área principal de la app en cada tramo. */
const MAIN = [
  { from: ACT.live, to: CLICK.finalizar + 4, render: (f: number) => <Live frame={f} />, nav: "Reuniones" as const },
  { from: CLICK.finalizar + 4, to: ACT.detail, render: (f: number) => <Processing frame={f} />, nav: "Reuniones" as const },
  { from: ACT.detail, to: CLICK.navAsk, render: (f: number) => <Detail frame={f} />, nav: "Reuniones" as const },
  { from: CLICK.navAsk, to: CLICK.fuente, render: (f: number) => <Ask frame={f} />, nav: "Preguntale a Echo" as const },
  { from: CLICK.fuente, to: CLICK.navFamilias, render: (f: number) => <Detail frame={f} sourceJump />, nav: "Reuniones" as const },
  { from: CLICK.navFamilias, to: Infinity, render: (f: number) => <Families frame={f} />, nav: "Familias" as const },
];

export const EchoDemo = () => {
  useFonts();
  const frame = useCurrentFrame();
  const nav = MAIN.find((m) => frame >= m.from && frame < m.to)?.nav ?? "Reuniones";

  return (
    <AbsoluteFill className="echo-demo" style={{ backgroundColor: "#fafbfc" }}>
      <Audio
        src={staticFile("music.mp3")}
        volume={(f) => interpolate(f, [0, 8, DURATION - 70, DURATION - 2], [0, 1, 1, 0], { extrapolateRight: "clamp" })}
      />
      <Captions frame={frame} />

      <Surface frame={frame}>
        {(surface) => {
          const notes = presence(frame, -30, ACT.modal, 1, 10);
          const loopNotes = presence(frame, ACT.loop + 8, Infinity, 16);
          const modal = presence(frame, ACT.modal + 8, ACT.live, 12, 10);
          const app = presence(frame, ACT.live + 8, ACT.logo, 14, 10);
          const tile = presence(frame, ACT.logo + 6, ACT.loop, 12, 10);
          return (
            <>
              {notes.visible && (
                <Fill width={NOTES_VIRTUAL.w} height={NOTES_VIRTUAL.h} surface={surface} style={notes.style}>
                  <Notes frame={frame} />
                </Fill>
              )}
              {loopNotes.visible && (
                <Fill width={NOTES_VIRTUAL.w} height={NOTES_VIRTUAL.h} surface={surface} style={loopNotes.style}>
                  <Notes frame={0} />
                </Fill>
              )}
              {modal.visible && (
                <Fill width={MODAL_W} height={MODAL_H} surface={surface} style={modal.style}>
                  <NewMeeting frame={frame} />
                </Fill>
              )}
              {app.visible && (
                <AppViewport frame={frame} surface={surface} style={app.style}>
                  <div className="absolute inset-0 overflow-hidden bg-[#fafbfc]" style={{ width: APP_W, height: APP_H }}>
                    <Sidebar active={nav} frame={frame} />
                    {MAIN.map((screen) => {
                      const shown = presence(frame, screen.from, screen.to, 12, 8);
                      if (!shown.visible) return null;
                      return (
                        <div key={screen.from} className="absolute inset-0" style={shown.style}>
                          {screen.render(frame)}
                        </div>
                      );
                    })}
                  </div>
                </AppViewport>
              )}
              {tile.visible && (
                <div className="absolute inset-0 flex items-center justify-center" style={tile.style}>
                  <Face size={surface.w} frame={frame} color="#fafbfc" blinkAt={[B(56.4)]} />
                </div>
              )}
            </>
          );
        }}
      </Surface>

      <LogoLockup frame={frame} />
      <Cursor frame={frame} />
    </AbsoluteFill>
  );
};
