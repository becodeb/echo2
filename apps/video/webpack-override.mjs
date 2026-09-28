// Override de webpack compartido por remotion.config.ts (CLI) y
// scripts/stills.mjs (render programático del QA).
import path from "node:path";
import { enableTailwind } from "@remotion/tailwind-v4";

// La CLI empaqueta la config como CJS (sin import.meta): las rutas salen del
// directorio de trabajo, que en los dos casos es apps/video.
const root = process.cwd();

// Tailwind 4 con los mismos tokens que la web (src/demo/demo.css). React se
// resuelve siempre desde este proyecto: la demo importa los componentes reales
// de apps/web/src y sin esto traerían su propia copia de React.
export const webpackOverride = (config) => {
  const withTailwind = enableTailwind(config);
  return {
    ...withTailwind,
    resolve: {
      ...withTailwind.resolve,
      alias: {
        ...(withTailwind.resolve?.alias ?? {}),
        react: path.join(root, "node_modules/react"),
        "react-dom": path.join(root, "node_modules/react-dom"),
      },
    },
  };
};
