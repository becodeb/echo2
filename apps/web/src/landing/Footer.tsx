import { Link } from "react-router-dom";
import { Reveal } from "./Reveal";

export function Closing() {
  return (
    <Reveal className="mx-auto max-w-6xl border-t border-ink-200 px-6 py-24 md:px-12 md:py-32">
      <h2 className="max-w-2xl text-4xl font-semibold tracking-tighter text-ink-950 md:text-6xl">
        Empezá con tu próxima reunión.
      </h2>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link to="/register" className="btn btn-ink">
          Crear cuenta
        </Link>
        <Link to="/login" className="btn btn-ghost">
          Ingresar
        </Link>
      </div>
    </Reveal>
  );
}

export function Footer() {
  return (
    <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-10 text-sm text-ink-500 md:px-12">
      <span className="font-semibold tracking-tight text-ink-950">Echo</span>
      <span>La reunión termina. Echo recuerda.</span>
    </footer>
  );
}
