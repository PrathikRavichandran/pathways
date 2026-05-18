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
  reset: { en: "New chat", es: "Nueva charla" },
  reset_confirm: {
    en: "Start a fresh conversation? Your current intake will be lost.",
    es: "¿Empezar una conversación nueva? Se perderá el intake actual.",
  },
  install_app: { en: "Install app", es: "Instalar app" },
  install_hint: {
    en: "Install Pathways for offline access.",
    es: "Instala Pathways para acceso sin internet.",
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
    en: "Free and confidential. Texas-only.",
    es: "Gratis y confidencial. Solo para Texas.",
  },
  stage_hint_name: {
    en: "Step 1 of 3 · your name",
    es: "Paso 1 de 3 · tu nombre",
  },
  stage_hint_location: {
    en: "Step 2 of 3 · where you are",
    es: "Paso 2 de 3 · dónde estás",
  },
  stage_hint_need: {
    en: "Step 3 of 3 · what you need most",
    es: "Paso 3 de 3 · qué necesitas más",
  },
  // Welcome screen
  welcome_eyebrow: {
    en: "Texas reentry navigator",
    es: "Navegador de reingreso en Texas",
  },
  welcome_title: {
    en: "You're not figuring this out alone.",
    es: "No tienes que resolver esto solo.",
  },
  welcome_body: {
    en: "Tell me what you need most right now. I'll point you to real, verified help in Texas: housing, food, work, ID, benefits, legal aid.",
    es: "Cuéntame qué necesitas más en este momento. Te conectaré con ayuda real y verificada en Texas: vivienda, comida, trabajo, identificación, beneficios y asistencia legal.",
  },
  welcome_cta: {
    en: "Let's get started",
    es: "Empecemos",
  },
  quick_housing: { en: "I need housing", es: "Necesito vivienda" },
  quick_food: { en: "I need food", es: "Necesito comida" },
  quick_work: { en: "I need work", es: "Necesito trabajo" },
  quick_id: { en: "I need my ID", es: "Necesito mi identificación" },
  privacy_note: {
    en: "Free, confidential. We never share your number.",
    es: "Gratis, confidencial. Nunca compartimos tu número.",
  },

  // Menu + pages
  menu_open: { en: "Open menu", es: "Abrir menú" },
  menu_close: { en: "Close menu", es: "Cerrar menú" },
  back_to_chat: { en: "Back to chat", es: "Volver al chat" },
  menu_about: { en: "About Pathways", es: "Acerca de Pathways" },
  menu_learn: { en: "Understanding reentry", es: "Entendiendo el reingreso" },
  menu_emergency: { en: "Emergency contacts", es: "Contactos de emergencia" },
  menu_privacy: { en: "Privacy & trust", es: "Privacidad y confianza" },

  // Resource map view
  map_title: { en: "Nearby on the map", es: "Cerca de ti en el mapa" },
  map_open_in_google_maps: {
    en: "Open in Google Maps",
    es: "Abrir en Google Maps",
  },
  map_distance_suffix: { en: "mi away", es: "millas" },
  map_attribution_note: {
    en: "Map data © OpenStreetMap contributors",
    es: "Datos del mapa © colaboradores de OpenStreetMap",
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
