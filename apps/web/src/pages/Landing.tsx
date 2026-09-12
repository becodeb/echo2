import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "../landing/landing.css";
import { Hero } from "../landing/Hero";
import { Steps } from "../landing/Steps";
import { Specimens } from "../landing/Specimens";
import { Acta } from "../landing/Acta";
import { Privacy } from "../landing/Privacy";
import { Ask } from "../landing/Ask";
import { Providers } from "../landing/Providers";
import { Closing, Footer } from "../landing/Footer";

/** Landing pública de Echo. El hero es el video de la cara; después, cómo se
 *  usa, qué queda de una reunión, el acta, la privacidad, el chat y los
 *  proveedores. Pensada para educación (entrevistas con familias) sin dejar
 *  afuera cualquier otra reunión. */
export default function Landing() {
  return (
    <main className="landing bg-[#fafbfc] text-ink-950 antialiased">
      <Hero />
      <Steps />
      <Specimens />
      <Acta />
      <Privacy />
      <Ask />
      <Providers />
      <Closing />
      <Footer />
    </main>
  );
}
