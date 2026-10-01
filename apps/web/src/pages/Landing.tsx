import "@fontsource-variable/geist-mono";
import "../landing/landing.css";
import { useTitle } from "../lib/useTitle";
import { Hero } from "../landing/Hero";
import { Steps } from "../landing/Steps";
import { Demo } from "../landing/Demo";
import { Specimens } from "../landing/Specimens";
import { Acta } from "../landing/Acta";
import { Privacy } from "../landing/Privacy";
import { Ask } from "../landing/Ask";
import { Pricing } from "../landing/Pricing";
import { Faq } from "../landing/Faq";
import { Closing, Footer } from "../landing/Footer";

/** Landing pública de Echo. El hero es el video de la cara; después, cómo se
 *  usa, qué queda de una reunión, el acta, la privacidad, el chat, los precios
 *  y las preguntas frecuentes. Pensada para colegios (entrevistas con
 *  familias, reuniones del equipo docente). */
export default function Landing() {
  useTitle(null);
  return (
    <main className="landing bg-[#fafbfc] text-ink-950 antialiased">
      <Hero />
      <Steps />
      <Demo />
      <Specimens />
      <Acta />
      <Privacy />
      <Ask />
      <Pricing />
      <Faq />
      <Closing />
      <Footer />
    </main>
  );
}
