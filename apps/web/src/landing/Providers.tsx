import {
  siAnthropic,
  siDeepgram,
  siGoogledrive,
  siGooglegemini,
  siOllama,
  siOpenrouter,
  type SimpleIcon,
} from "simple-icons";
import { Reveal } from "./Reveal";

const LOGOS: SimpleIcon[] = [siAnthropic, siGooglegemini, siOpenrouter, siOllama, siDeepgram, siGoogledrive];

export function Providers() {
  return (
    <Reveal className="mx-auto max-w-6xl px-6 py-24 md:px-12 md:py-32">
      <h2 className="text-3xl font-semibold tracking-tighter text-ink-950 md:text-4xl">
        Con el proveedor que ya usás
      </h2>
      <p className="mt-4 max-w-xl leading-relaxed text-ink-600 md:text-lg">
        Ningún modelo viene fijo. Cada organización configura su modelo de lenguaje, su motor de voz y
        sus embeddings.
      </p>
      <ul className="mt-12 flex flex-wrap items-center gap-x-12 gap-y-8 text-ink-700">
        {LOGOS.map((icon) => (
          <li key={icon.slug} title={icon.title}>
            <svg role="img" viewBox="0 0 24 24" className="h-7 w-auto fill-current" aria-label={icon.title}>
              <path d={icon.path} />
            </svg>
          </li>
        ))}
      </ul>
      <p className="mt-10 text-sm text-ink-500">
        También OpenAI, Groq, whisper.cpp y cualquier servidor de voz compatible.
      </p>
    </Reveal>
  );
}
