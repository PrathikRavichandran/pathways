import type { Lang } from "../i18n";

type Entry = { term: string; explain: string };

const TERMS_EN: Entry[] = [
  { term: "Returning citizen",
    explain: "A person who has been released from prison or jail and is rebuilding their life on the outside. The term most reentry workers prefer." },
  { term: "Reentry",
    explain: "The first weeks and months after release. The window where housing, ID, work, benefits, and parole reporting all collide and where the right help makes a big difference." },
  { term: "Parole",
    explain: "Conditional release before the full sentence is over, supervised by a parole officer. Different from probation (which usually means no prison time at all)." },
  { term: "Probation",
    explain: "A sentence served in the community, supervised, instead of going to prison. Usually decided at sentencing." },
  { term: "Deferred adjudication",
    explain: "A Texas-specific path: you plead but the judge defers conviction. Complete the conditions and the case is dismissed (no conviction on your record), but you still went through the system." },
  { term: "Expunction",
    explain: "Completely erasing a charge from your record. Texas allows this only in narrow cases (Code of Criminal Procedure Ch. 55). Most convictions cannot be expunged." },
  { term: "Order of non-disclosure",
    explain: "A court order that hides certain records from most public background checks (Texas Government Code Ch. 411). More common than expunction." },
  { term: "NICCC",
    explain: "National Inventory of Collateral Consequences of Conviction. A federal database listing every law that restricts what someone with a conviction can do (jobs, licenses, voting, benefits). Pathways uses NICCC as a source of truth." },
  { term: "TWC",
    explain: "Texas Workforce Commission. Runs ~200 job centers across Texas and includes a formal reentry initiative for people with records." },
  { term: "HHSC",
    explain: "Texas Health and Human Services Commission. Decides SNAP (food stamps), Medicaid, TANF, and other benefits." },
  { term: "TDCJ",
    explain: "Texas Department of Criminal Justice. Runs the state prisons. Provides a release packet, $50-$100 gate money, and a temporary ID at release." },
  { term: "Fair-chance hiring",
    explain: "Employer practice of considering applicants individually instead of auto-rejecting anyone with a record. The federal Bonding Program also covers fair-chance hires for free for the first six months." },
  { term: "SNAP felony rule",
    explain: "Federal law bans drug felons from SNAP unless the state opts out. Texas DID opt out (with conditions): most people with a Texas drug felony CAN get SNAP. A common misconception keeps people from food they qualify for." },
  { term: "Occupational license evaluation letter",
    explain: "Under Texas Occupations Code §53.102, you can ask any licensing board to tell you upfront whether your record will disqualify you, before you spend tuition or fees. Use it." },
];

const FAQS_EN: Entry[] = [
  { term: "What's my first step after release?",
    explain: "Three things in roughly this order: a place to sleep tonight, a state ID, and a way to reach your parole officer (if applicable). Pathways helps with all three." },
  { term: "What if I don't have ID?",
    explain: "Your TDCJ release packet includes a temporary ID. To get a Texas DL or state ID, use Form DL-43 for the reduced-fee version. We can point you to the closest DPS office." },
  { term: "Can my felony be cleared?",
    explain: "Most felonies cannot be expunged in Texas, but many can be non-disclosed (Gov. Code 411). Eligibility depends on offense type, sentence, and time elapsed. Ask us to walk through it." },
  { term: "Can I vote with a felony in Texas?",
    explain: "Yes, once you have completed your full sentence including parole and probation. You're not eligible while still on paper." },
  { term: "Can I get a job with my record?",
    explain: "Yes. Most jobs don't have a legal bar. Some licensed trades (nursing, real estate, certain CDL endorsements) have restrictions. Use the evaluation letter (above) to know before you apply." },
  { term: "What if I'm in crisis right now?",
    explain: "Open Emergency Contacts from the menu. 988 is the Suicide & Crisis Lifeline (call or text), 911 is for immediate danger, 211 is Texas social services." },
];

const TERMS_ES: Entry[] = [
  { term: "Ciudadano que regresa",
    explain: "Una persona que ha sido liberada de la cárcel o prisión y está reconstruyendo su vida afuera." },
  { term: "Reingreso",
    explain: "Las primeras semanas y meses después de salir. La ventana donde vivienda, identificación, trabajo, beneficios, y reportarse con libertad condicional ocurren al mismo tiempo." },
  { term: "Libertad condicional (parole)",
    explain: "Liberación antes de cumplir la sentencia completa, supervisada por un oficial. Diferente de probatoria (que normalmente significa no ir a prisión)." },
  { term: "Probatoria (probation)",
    explain: "Una sentencia cumplida en la comunidad, bajo supervisión, en vez de ir a prisión." },
  { term: "Expurgación",
    explain: "Borrar completamente un cargo de tu récord. Texas lo permite solo en casos limitados (Código de Procedimiento Penal Cap. 55)." },
  { term: "Orden de no divulgación",
    explain: "Una orden judicial que esconde ciertos registros de la mayoría de las verificaciones de antecedentes públicas (Código Gubernamental Cap. 411 de Texas)." },
  { term: "TWC",
    explain: "Comisión de Fuerza Laboral de Texas. Maneja ~200 centros de trabajo y tiene una iniciativa formal de reingreso." },
  { term: "HHSC",
    explain: "Comisión de Salud y Servicios Humanos de Texas. Decide SNAP, Medicaid, TANF y otros beneficios." },
  { term: "TDCJ",
    explain: "Departamento de Justicia Criminal de Texas. Maneja las prisiones estatales." },
  { term: "SNAP y delitos de drogas",
    explain: "Texas se retiró de la prohibición federal: la mayoría de las personas con un delito de drogas en Texas SÍ pueden recibir SNAP. Pregúntanos." },
];

const FAQS_ES: Entry[] = [
  { term: "¿Cuál es mi primer paso después de salir?",
    explain: "Tres cosas en este orden: un lugar para dormir esta noche, una identificación estatal, y una manera de contactar a tu oficial de libertad condicional si aplica." },
  { term: "¿Y si no tengo identificación?",
    explain: "Tu paquete de salida de TDCJ incluye una identificación temporal. Para una licencia o ID de Texas, usa el Formulario DL-43 para la versión de costo reducido." },
  { term: "¿Puedo limpiar mi récord?",
    explain: "Muchos delitos no pueden expurgarse en Texas, pero muchos sí pueden no divulgarse. La elegibilidad depende del tipo de delito, sentencia, y tiempo transcurrido." },
  { term: "¿Puedo votar con un récord en Texas?",
    explain: "Sí, una vez que has terminado tu sentencia completa incluyendo libertad condicional y probatoria." },
  { term: "¿Y si estoy en crisis ahora mismo?",
    explain: "Abre Contactos de Emergencia desde el menú. 988 es la línea de crisis y suicidio (llama o textea), 911 es para peligro inmediato, 211 es servicios sociales de Texas." },
];

function Glossary({ heading, entries }: { heading: string; entries: Entry[] }) {
  return (
    <section>
      <h2 className="font-display text-xl font-semibold text-ink-700 dark:text-cream-100 mb-3">
        {heading}
      </h2>
      <dl className="space-y-3">
        {entries.map((e) => (
          <div
            key={e.term}
            className="rounded-2xl border border-cream-300 bg-cream-50 p-4 dark:border-ink-700 dark:bg-ink-800"
          >
            <dt className="font-semibold text-ink-700 dark:text-cream-100">
              {e.term}
            </dt>
            <dd className="mt-1 text-sm leading-relaxed text-ink-500 dark:text-cream-300">
              {e.explain}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function LearnPage({ lang }: { lang: Lang }) {
  const isEs = lang === "es";
  return (
    <article className="space-y-6">
      <header className="text-center">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-teal-600 dark:text-teal-300">
          {isEs ? "Aprende" : "Learn"}
        </p>
        <h1 className="mt-2 font-display text-3xl font-semibold leading-tight text-ink-700 dark:text-cream-100">
          {isEs ? "Entendiendo el reingreso" : "Understanding reentry"}
        </h1>
        <p className="mt-3 text-sm text-ink-500 dark:text-cream-300">
          {isEs
            ? "Términos y preguntas que aparecen mucho. En lenguaje sencillo."
            : "Terms and questions that come up a lot. In plain language."}
        </p>
      </header>

      <Glossary
        heading={isEs ? "Glosario" : "Glossary"}
        entries={isEs ? TERMS_ES : TERMS_EN}
      />
      <Glossary
        heading={isEs ? "Preguntas frecuentes" : "Frequently asked questions"}
        entries={isEs ? FAQS_ES : FAQS_EN}
      />
    </article>
  );
}
