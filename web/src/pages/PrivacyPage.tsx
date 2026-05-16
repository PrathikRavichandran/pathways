import type { Lang } from "../i18n";

export function PrivacyPage({ lang }: { lang: Lang }) {
  const isEs = lang === "es";
  return (
    <article className="space-y-6">
      <header className="text-center">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-teal-600 dark:text-teal-300">
          {isEs ? "Privacidad" : "Privacy"}
        </p>
        <h1 className="mt-2 font-display text-3xl font-semibold leading-tight text-ink-700 dark:text-cream-100">
          {isEs
            ? "Esto es lo que sabemos de ti."
            : "Here's what we actually know about you."}
        </h1>
      </header>

      <div className="space-y-4 leading-relaxed text-ink-600 dark:text-cream-200">
        {isEs ? (
          <>
            <p>
              <strong>No guardamos tu número de teléfono tal como es.</strong>{" "}
              Lo convertimos a un código de una sola dirección (un hash con
              sal) antes de guardarlo. Si nuestra base de datos se filtrara
              mañana, nadie podría recuperar tu número desde lo que guardamos.
            </p>
            <p>
              <strong>No guardamos tus mensajes para los aliados.</strong>{" "}
              Las organizaciones aliadas que ven el panel de control ven solo
              números agregados: cuántas personas pidieron vivienda esta
              semana, cuántas pidieron comida. Nunca el texto de tus mensajes,
              nunca tu nombre, nunca tu identificación.
            </p>
            <p>
              <strong>No vendemos nada. Nunca.</strong> Esto es un proyecto
              sin fines de lucro. No hay anunciantes, no hay datos para
              vender.
            </p>
            <p>
              <strong>Tú decides cuándo parar.</strong> Envía{" "}
              <code className="rounded bg-cream-200 px-1.5 py-0.5 text-sm dark:bg-ink-700">
                STOP
              </code>{" "}
              en cualquier momento para no recibir más mensajes. Nunca lo
              cuestionaremos.
            </p>
            <p>
              <strong>Para auditoría interna,</strong> sí mantenemos un
              registro completo de las conversaciones (mensaje, respuesta,
              fuentes citadas) para poder corregir errores y mantener la
              calidad. Ese registro está cifrado y solo el operador del
              sistema lo puede leer, no los aliados.
            </p>
            <p>
              <strong>En crisis,</strong> el sistema escala
              automáticamente a un humano. Eso significa que la conversación
              puede ser revisada por una persona real para asegurar que
              recibiste la ayuda correcta.
            </p>
          </>
        ) : (
          <>
            <p>
              <strong>We don't store your phone number as-is.</strong> We
              convert it to a one-way code (a salted hash) before saving. If
              our database leaked tomorrow, no one could recover your number
              from what we have.
            </p>
            <p>
              <strong>We don't show your messages to partners.</strong>{" "}
              Partner organizations that view the dashboard see only
              aggregated numbers: how many people asked for housing this week,
              how many asked for food. Never your message text, never your
              name, never your ID.
            </p>
            <p>
              <strong>We don't sell anything. Ever.</strong> This is a
              non-profit project. No advertisers, no data to sell.
            </p>
            <p>
              <strong>You decide when to stop.</strong> Text{" "}
              <code className="rounded bg-cream-200 px-1.5 py-0.5 text-sm dark:bg-ink-700">
                STOP
              </code>{" "}
              any time and we'll never message you again. We won't push back.
            </p>
            <p>
              <strong>For internal audit,</strong> we do keep a full record of
              the conversation (message, reply, sources cited) so we can fix
              mistakes and improve quality. That record is encrypted and only
              the system operator can read it, not partners.
            </p>
            <p>
              <strong>In a crisis,</strong> the system automatically escalates
              to a human. That means the conversation may be reviewed by a
              real person to make sure you got the right help.
            </p>
          </>
        )}
      </div>

      <p className="text-xs text-ink-400 dark:text-cream-400 text-center">
        {isEs ? (
          <>
            Curioso de cómo funciona técnicamente?{" "}
            <a
              href="https://github.com/PrathikRavichandran/pathways"
              target="_blank"
              rel="noopener noreferrer"
              className="text-teal-700 underline hover:text-teal-800 dark:text-teal-300"
            >
              Todo está abierto en GitHub
            </a>
            .
          </>
        ) : (
          <>
            Curious how it works under the hood?{" "}
            <a
              href="https://github.com/PrathikRavichandran/pathways"
              target="_blank"
              rel="noopener noreferrer"
              className="text-teal-700 underline hover:text-teal-800 dark:text-teal-300"
            >
              Everything is open on GitHub
            </a>
            .
          </>
        )}
      </p>
    </article>
  );
}
