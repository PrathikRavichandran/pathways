// Pathways PWA: bilingual UI strings.
// Server-generated reply text is already in the right language (the
// `language` field on the TurnResponse drives the rendered HTML
// direction and lang attribute).

export type Lang = "en" | "es";

export const T = {
  app_title: { en: "Pathways", es: "Pathways" },
  app_subtitle: {
    en: "Help finding housing, food, work, ID, benefits, and legal aid in Texas.",
    es: "Ayuda con vivienda, comida, trabajo, identificación, beneficios y asistencia legal en Texas.",
  },
  input_placeholder: {
    en: "Tell me what you need most right now…",
    es: "Cuéntame qué necesitas más en este momento…",
  },
  send: { en: "Send", es: "Enviar" },
  sending: { en: "Sending…", es: "Enviando…" },
  reset: { en: "New conversation", es: "Nueva conversación" },
  reset_confirm: {
    en: "Start a fresh conversation? Your current intake will be lost.",
    es: "¿Empezar una conversación nueva? Se perderá el intake actual.",
  },
  install_app: { en: "Install app", es: "Instalar app" },
  install_hint: {
    en: "Install Pathways to your home screen for offline access.",
    es: "Instala Pathways en tu pantalla de inicio para acceso sin internet.",
  },
  install_later: { en: "Maybe later", es: "Tal vez después" },
  intent_greeting: {
    en: "Hi. I'm Pathways. Tell me what you need help with.",
    es: "Hola. Soy Pathways. Cuéntame con qué necesitas ayuda.",
  },
  error_generic: {
    en: "Something went wrong on my end. Try again in a moment.",
    es: "Algo salió mal. Inténtalo de nuevo en un momento.",
  },
  offline_warning: {
    en: "You appear to be offline. Your last reply is shown below.",
    es: "Parece que no tienes conexión. Tu última respuesta se muestra abajo.",
  },
  call: { en: "Call", es: "Llamar" },
  visit: { en: "Visit website", es: "Visitar sitio" },
  about: {
    en: "Built as a Claude Code architecture demo. Open source on GitHub.",
    es: "Construido como demo de arquitectura de Claude Code. Open source en GitHub.",
  },
  stage_hint_name: {
    en: "Step 1 of 3: telling me your name",
    es: "Paso 1 de 3: tu nombre",
  },
  stage_hint_location: {
    en: "Step 2 of 3: where you are",
    es: "Paso 2 de 3: dónde estás",
  },
  stage_hint_need: {
    en: "Step 3 of 3: what you need most",
    es: "Paso 3 de 3: qué necesitas más",
  },
};

export function t(key: keyof typeof T, lang: Lang): string {
  return T[key][lang] || T[key].en;
}

export function stageHint(
  stage: string | null,
  lang: Lang,
): string | null {
  if (!stage) return null;
  if (stage === "collect_name") return t("stage_hint_name", lang);
  if (stage === "collect_location") return t("stage_hint_location", lang);
  if (stage === "collect_need") return t("stage_hint_need", lang);
  return null;
}
