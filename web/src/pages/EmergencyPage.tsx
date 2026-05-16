import type { Lang } from "../i18n";

type Contact = {
  number: string;
  name: { en: string; es: string };
  blurb: { en: string; es: string };
  text?: boolean;
};

const CONTACTS: Contact[] = [
  {
    number: "911",
    name: {
      en: "Police, fire, medical emergency",
      es: "Policía, bomberos, emergencia médica",
    },
    blurb: {
      en: "Call for immediate danger to life or safety, fire, or a medical emergency.",
      es: "Llama si hay peligro inmediato para tu vida o seguridad, incendio, o emergencia médica.",
    },
  },
  {
    number: "988",
    name: {
      en: "Suicide & Crisis Lifeline",
      es: "Línea de Crisis y Suicidio",
    },
    blurb: {
      en: "Free, confidential, 24/7. Call or text. Spanish available.",
      es: "Gratis, confidencial, 24/7. Llama o textea. Disponible en español.",
    },
    text: true,
  },
  {
    number: "211",
    name: {
      en: "211 Texas — social services",
      es: "211 Texas — servicios sociales",
    },
    blurb: {
      en: "Free 24/7 referral line for housing, food, utilities, health care, and more across Texas.",
      es: "Línea gratuita de referencias 24/7 para vivienda, comida, servicios públicos, salud y más en todo Texas.",
    },
  },
  {
    number: "1-800-799-7233",
    name: {
      en: "National Domestic Violence Hotline",
      es: "Línea Nacional de Violencia Doméstica",
    },
    blurb: {
      en: "Free, confidential, 24/7. Spanish + 200+ languages via interpreter.",
      es: "Gratis, confidencial, 24/7. Español y más de 200 idiomas con intérprete.",
    },
    text: true,
  },
  {
    number: "1-877-565-8860",
    name: {
      en: "Trans Lifeline",
      es: "Trans Lifeline",
    },
    blurb: {
      en: "Peer-support hotline by and for trans people. Trans-affirming, non-carceral.",
      es: "Línea de apoyo por y para personas trans. Afirmativa, sin involucrar policía.",
    },
  },
  {
    number: "1-866-488-7386",
    name: {
      en: "The Trevor Project",
      es: "The Trevor Project",
    },
    blurb: {
      en: "Crisis support for LGBTQ+ youth. Call, text START to 678678, or chat.",
      es: "Apoyo de crisis para jóvenes LGBTQ+. Llama, textea START al 678678, o chatea.",
    },
    text: true,
  },
  {
    number: "988 (then press 1)",
    name: {
      en: "Veterans Crisis Line",
      es: "Línea de Crisis para Veteranos",
    },
    blurb: {
      en: "Free, confidential. For veterans, service members, and their loved ones.",
      es: "Gratis, confidencial. Para veteranos, miembros de servicio y sus seres queridos.",
    },
    text: true,
  },
  {
    number: "1-800-222-1222",
    name: {
      en: "Poison Control",
      es: "Control de Envenenamiento",
    },
    blurb: {
      en: "If you or someone else swallowed, breathed, or touched something dangerous.",
      es: "Si tú u otra persona tragó, inhaló, o tocó algo peligroso.",
    },
  },
];

export function EmergencyPage({ lang }: { lang: Lang }) {
  const isEs = lang === "es";
  return (
    <article className="space-y-6">
      <header className="text-center">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-marigold-500">
          {isEs ? "Emergencia" : "Emergency"}
        </p>
        <h1 className="mt-2 font-display text-3xl font-semibold leading-tight text-ink-700 dark:text-cream-100">
          {isEs ? "Si necesitas ayuda ahora" : "If you need help right now"}
        </h1>
        <p className="mt-3 text-sm text-ink-500 dark:text-cream-300">
          {isEs
            ? "Estos números son gratuitos y confidenciales. Toca para llamar."
            : "These numbers are free and confidential. Tap to call."}
        </p>
      </header>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {CONTACTS.map((c) => {
          const tel = c.number.split(" ")[0].replace(/[^\d+]/g, "");
          return (
            <a
              key={c.number}
              href={`tel:${tel}`}
              className="block rounded-2xl border border-cream-300 bg-cream-50 p-4 shadow-soft transition hover:border-marigold-400 hover:shadow-lift dark:border-ink-700 dark:bg-ink-800"
            >
              <div className="flex items-baseline justify-between gap-3">
                <div className="font-display text-2xl font-semibold text-ink-700 dark:text-cream-100">
                  {c.number}
                </div>
                {c.text && (
                  <span className="shrink-0 rounded-full bg-marigold-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-marigold-700 dark:bg-marigold-700/20 dark:text-marigold-200">
                    {isEs ? "Texto" : "Text"}
                  </span>
                )}
              </div>
              <div className="mt-2 text-sm font-semibold text-ink-700 dark:text-cream-100">
                {c.name[lang]}
              </div>
              <p className="mt-1 text-sm leading-relaxed text-ink-500 dark:text-cream-300">
                {c.blurb[lang]}
              </p>
            </a>
          );
        })}
      </div>

      <div className="rounded-2xl border border-marigold-200 bg-marigold-50/60 p-4 text-sm leading-relaxed text-ink-700 dark:border-marigold-700/40 dark:bg-marigold-700/10 dark:text-cream-200">
        {isEs ? (
          <>
            <strong>En cualquier crisis grave:</strong> llama al 911 si hay
            peligro inmediato. Llama o textea al 988 si estás pensando en
            hacerte daño. Estás en buenas manos. No estás solo.
          </>
        ) : (
          <>
            <strong>For any serious crisis:</strong> call 911 for immediate
            danger. Call or text 988 if you're thinking about hurting yourself.
            You are in good hands. You are not alone.
          </>
        )}
      </div>
    </article>
  );
}
