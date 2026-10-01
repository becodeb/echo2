import { EchoChat } from "../components/EchoChat";

/** "Preguntale a Echo" a pantalla completa: el mismo chat del panel, más ancho. */
export default function AskEcho() {
  return (
    <div className="flex h-full min-h-0 flex-col pt-2">
      <EchoChat wide />
    </div>
  );
}
