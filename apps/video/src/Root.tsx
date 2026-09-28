import { Composition } from "remotion";
import { EchoDemo } from "./demo/EchoDemo";
import { FPS as DEMO_FPS, HEIGHT, TOTAL, WIDTH } from "./demo/timeline";
import { EchoOjos } from "./EchoOjos";
import { Variante, VARIANTES } from "./Variantes";

const FPS = 30;

export const Root = () => (
  <>
    {/* La demo de producto (STORYBOARD.md): el hero de la landing + 30 s de demo, a 60 fps. */}
    <Composition
      id="EchoDemo"
      component={EchoDemo}
      durationInFrames={TOTAL}
      fps={DEMO_FPS}
      width={WIDTH}
      height={HEIGHT}
    />
    <Composition
      id="EchoOjos"
      component={EchoOjos}
      durationInFrames={120}
      fps={FPS}
      width={1920}
      height={1080}
    />
    {VARIANTES.map((v, i) => {
      const code = v.code ?? "v" + String(i + 1).padStart(2, "0");
      const frames = Math.round(v.segundos * FPS);
      return (
        <>
          <Composition
            key={v.id}
            id={`${code}-${v.id}`}
            component={Variante}
            defaultProps={{ variant: v.id }}
            durationInFrames={frames}
            fps={FPS}
            width={1920}
            height={1080}
          />
          {v.vertical && (
            <Composition
              key={`${v.id}-vertical`}
              id={`${code}-${v.id}-vertical`}
              component={Variante}
              defaultProps={{ variant: v.id }}
              durationInFrames={frames}
              fps={FPS}
              width={1080}
              height={1920}
            />
          )}
        </>
      );
    })}
  </>
);
