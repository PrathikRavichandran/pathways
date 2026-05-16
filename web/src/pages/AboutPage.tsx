import type { Lang } from "../i18n";
import { LogoMark } from "../Logo";

export function AboutPage({ lang }: { lang: Lang }) {
  return (
    <article className="space-y-6">
      <div className="flex items-center justify-center pb-2">
        <LogoMark size={80} withGlow />
      </div>
      <header className="text-center">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-teal-600 dark:text-teal-300">
          {lang === "es" ? "Acerca de" : "About"}
        </p>
        <h1 className="mt-2 font-display text-3xl font-semibold leading-tight text-ink-700 dark:text-cream-100 sm:text-4xl">
          {lang === "es"
            ? "Un guía gratuito y confidencial."
            : "A free, confidential navigator."}
        </h1>
      </header>

      {lang === "es" ? (
        <div className="space-y-4 leading-relaxed text-ink-600 dark:text-cream-200">
          <p>
            Pathways es un guía conversacional para personas que salen de la
            cárcel en Texas. Te ayudamos a encontrar vivienda, comida, trabajo,
            identificación, beneficios y asistencia legal en los primeros
            días después de tu salida.
          </p>
          <p>
            Puedes usarnos por SMS (texto), por esta página web, o a través de
            un trabajador social de una organización aliada. Todo es gratis,
            todo es confidencial, y solo cubrimos Texas.
          </p>
          <p>
            Lo que NO somos: no somos abogados, ni médicos, ni oficiales de
            libertad condicional. Te explicamos cómo funcionan las reglas y te
            conectamos con la persona correcta cuando algo es legal o médico.
          </p>
          <p className="text-sm text-ink-500 dark:text-cream-300">
            Construido como una arquitectura abierta de Claude Code en{" "}
            <a
              href="https://github.com/PrathikRavichandran/pathways"
              className="text-teal-700 underline hover:text-teal-800 dark:text-teal-300"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub
            </a>
            .
          </p>
        </div>
      ) : (
        <div className="space-y-4 leading-relaxed text-ink-600 dark:text-cream-200">
          <p>
            Pathways is a conversational navigator for people leaving
            incarceration in Texas. We help you find housing, food, work, ID,
            benefits, and legal aid in the first few days after release, when
            things move fast and one missed step can cost a lot.
          </p>
          <p>
            You can reach us by SMS (text), through this web app, or through a
            caseworker at a partner organization. Everything is free, everything
            is confidential, and we only cover Texas.
          </p>
          <p>
            What we're not: we're not lawyers, doctors, or parole officers. We
            explain how the rules work and connect you to the right person when
            something is legal or medical.
          </p>
          <p className="text-sm text-ink-500 dark:text-cream-300">
            Built as an open Claude Code architecture on{" "}
            <a
              href="https://github.com/PrathikRavichandran/pathways"
              className="text-teal-700 underline hover:text-teal-800 dark:text-teal-300"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub
            </a>
            .
          </p>
        </div>
      )}
    </article>
  );
}
