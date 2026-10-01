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
        <Link to="/contacto?tema=ventas" className="btn btn-ghost">
          Para todo el colegio
        </Link>
      </div>
    </Reveal>
  );
}

export function Footer() {
  return (
    <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-10 text-sm text-ink-600 md:px-12">
      <span className="font-semibold tracking-tight text-ink-950">Echo</span>
      <nav className="flex flex-wrap gap-x-5 gap-y-2" aria-label="Más">
        <Link to="/contacto?tema=ventas" className="hover:text-ink-900">Contact sales</Link>
        <Link to="/contacto" className="hover:text-ink-900">Contacto</Link>
        <Link to="/legal/privacidad" className="hover:text-ink-900">Privacidad</Link>
        <Link to="/legal/terminos" className="hover:text-ink-900">Términos</Link>
      </nav>
      <span>La reunión termina. Echo recuerda.</span>
    </footer>
  );
}
