// Pathways PWA API client.
//
// Backend is the same FastAPI service the SMS channel hits. Phase 4
// endpoints live under /web/. The session_id is persisted in
// localStorage so a browser refresh continues the same intake.

const API_URL = (import.meta.env.VITE_API_URL as string | undefined) || "";

if (!API_URL) {
  // eslint-disable-next-line no-console
  console.warn(
    "[pathways] VITE_API_URL is not set; calls will go to relative paths. " +
      "Set it in .env.local for local dev or as a Vercel env var for production.",
  );
}

export interface ResourceCard {
  id: string;
  name: string;
  description: string | null;
  phone: string | null;
  url: string | null;
  category: string | null;
  distance_miles: number | null;
  languages: string[];
  // Coordinates for the map view. Statewide hotlines arrive with both
  // null and are silently omitted from the map (still shown in the list).
  lat: number | null;
  lon: number | null;
}

export interface TurnResponse {
  reply: string;
  language: "en" | "es";
  intake_stage: string | null;
  needs: string[];
  resources: ResourceCard[];
  escalated: boolean;
  escalation_reason: string | null;
}

export interface SessionResponse {
  session_id: string;
  thread_id: string;
}

const SESSION_KEY = "pathways.session_id";

export async function getOrCreateSession(
  languageHint?: "en" | "es",
): Promise<SessionResponse> {
  const cached = localStorage.getItem(SESSION_KEY);
  if (cached) {
    return { session_id: cached, thread_id: "" };
  }
  const res = await fetch(`${API_URL}/web/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language_hint: languageHint }),
  });
  if (!res.ok) {
    throw new Error(`Failed to create session: HTTP ${res.status}`);
  }
  const data: SessionResponse = await res.json();
  localStorage.setItem(SESSION_KEY, data.session_id);
  return data;
}

export function resetSession(): void {
  localStorage.removeItem(SESSION_KEY);
}

export async function sendTurn(
  sessionId: string,
  message: string,
): Promise<TurnResponse> {
  const res = await fetch(`${API_URL}/web/turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = body?.detail || "";
    } catch {
      /* ignore */
    }
    throw new Error(`HTTP ${res.status}${detail ? ": " + detail : ""}`);
  }
  return res.json();
}
