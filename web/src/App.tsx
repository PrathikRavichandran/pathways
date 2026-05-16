import { useEffect, useRef, useState } from "react";
import {
  getOrCreateSession,
  resetSession,
  sendTurn,
  type ResourceCard,
  type TurnResponse,
} from "./api";
import { type Lang, stageHint, t } from "./i18n";

type Bubble =
  | { kind: "user"; text: string; ts: number }
  | { kind: "bot"; text: string; resources: ResourceCard[]; lang: Lang; ts: number }
  | { kind: "stage"; text: string; ts: number }
  | { kind: "error"; text: string; ts: number };

// ---------------------------------------------------------------------------
// Install prompt (PWA)
// ---------------------------------------------------------------------------

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

function useInstallPrompt() {
  const [event, setEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState<boolean>(() => {
    return localStorage.getItem("pathways.install_dismissed") === "true";
  });

  useEffect(() => {
    function onBeforeInstall(e: Event) {
      e.preventDefault();
      setEvent(e as BeforeInstallPromptEvent);
    }
    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    return () =>
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
  }, []);

  return {
    canInstall: !!event && !dismissed,
    async install() {
      if (!event) return;
      await event.prompt();
      const choice = await event.userChoice;
      if (choice.outcome === "dismissed") {
        localStorage.setItem("pathways.install_dismissed", "true");
        setDismissed(true);
      }
      setEvent(null);
    },
    dismiss() {
      localStorage.setItem("pathways.install_dismissed", "true");
      setDismissed(true);
      setEvent(null);
    },
  };
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const [lang, setLang] = useState<Lang>(() => {
    const stored = localStorage.getItem("pathways.lang");
    if (stored === "es" || stored === "en") return stored;
    const browser = (navigator.language || "en").toLowerCase();
    return browser.startsWith("es") ? "es" : "en";
  });
  const [bubbles, setBubbles] = useState<Bubble[]>([
    { kind: "bot", text: t("intent_greeting", lang), resources: [], lang, ts: Date.now() },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const install = useInstallPrompt();
  const threadRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new bubble
  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, [bubbles, sending]);

  useEffect(() => {
    localStorage.setItem("pathways.lang", lang);
    document.documentElement.lang = lang;
  }, [lang]);

  // Create session on first mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await getOrCreateSession(lang);
        if (!cancelled) setSessionId(s.session_id);
      } catch (e) {
        if (!cancelled) {
          setBubbles((prev) => [
            ...prev,
            {
              kind: "error",
              text: t("error_generic", lang),
              ts: Date.now(),
            },
          ]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []); // run once

  async function onSend() {
    const text = input.trim();
    if (!text || sending || !sessionId) return;
    const userBubble: Bubble = { kind: "user", text, ts: Date.now() };
    setBubbles((prev) => [...prev, userBubble]);
    setInput("");
    setSending(true);
    try {
      const resp: TurnResponse = await sendTurn(sessionId, text);
      const botBubble: Bubble = {
        kind: "bot",
        text: resp.reply || "...",
        resources: resp.resources || [],
        lang: resp.language,
        ts: Date.now(),
      };
      setBubbles((prev) => [...prev, botBubble]);
      setStage(resp.intake_stage);
      // Persist server-detected language preference
      if (resp.language && resp.language !== lang) {
        setLang(resp.language);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "unknown";
      setBubbles((prev) => [
        ...prev,
        {
          kind: "error",
          text: `${t("error_generic", lang)} (${msg})`,
          ts: Date.now(),
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  function onReset() {
    if (!confirm(t("reset_confirm", lang))) return;
    resetSession();
    setSessionId(null);
    setBubbles([
      { kind: "bot", text: t("intent_greeting", lang), resources: [], lang, ts: Date.now() },
    ]);
    setStage(null);
    // re-mint a new session
    getOrCreateSession(lang).then((s) => setSessionId(s.session_id));
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  }

  const stageMsg = stageHint(stage, lang);

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <Header
        lang={lang}
        onToggleLang={() => setLang(lang === "en" ? "es" : "en")}
        onReset={onReset}
      />

      {install.canInstall && (
        <InstallBanner lang={lang} onInstall={install.install} onDismiss={install.dismiss} />
      )}

      {stageMsg && <StageBar text={stageMsg} />}

      <main
        ref={threadRef}
        className="chat-thread flex-1 overflow-y-auto px-4 py-4 pb-32"
      >
        <div className="mx-auto flex max-w-2xl flex-col gap-3">
          {bubbles.map((b, i) => (
            <BubbleView key={i} bubble={b} lang={lang} />
          ))}
          {sending && <TypingIndicator lang={lang} />}
        </div>
      </main>

      <footer className="fixed inset-x-0 bottom-0 border-t border-slate-200 bg-white p-3">
        <div className="mx-auto flex max-w-2xl items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={t("input_placeholder", lang)}
            rows={2}
            disabled={!sessionId || sending}
            className="flex-1 resize-none rounded-2xl border border-slate-300 bg-white px-4 py-3 text-base outline-none focus:border-pathways-600 focus:ring-2 focus:ring-pathways-100"
          />
          <button
            onClick={onSend}
            disabled={!sessionId || sending || !input.trim()}
            className="shrink-0 rounded-2xl bg-pathways-700 px-5 py-3 text-base font-medium text-white shadow-sm transition hover:bg-pathways-900 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {sending ? t("sending", lang) : t("send", lang)}
          </button>
        </div>
        <p className="mx-auto mt-2 max-w-2xl text-center text-xs text-slate-500">
          {t("about", lang)}
        </p>
      </footer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Header({
  lang,
  onToggleLang,
  onReset,
}: {
  lang: Lang;
  onToggleLang: () => void;
  onReset: () => void;
}) {
  return (
    <header className="sticky top-0 z-10 border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-2xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="h-9 w-9 rounded-xl bg-pathways-700 text-white flex items-center justify-center text-lg font-bold">
            P
          </div>
          <div>
            <div className="text-base font-semibold text-slate-900">
              {t("app_title", lang)}
            </div>
            <div className="text-xs text-slate-500 leading-tight max-w-[40ch]">
              {t("app_subtitle", lang)}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onToggleLang}
            aria-label="Toggle language"
            className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >
            {lang === "en" ? "ES" : "EN"}
          </button>
          <button
            onClick={onReset}
            aria-label="New conversation"
            className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >
            {t("reset", lang)}
          </button>
        </div>
      </div>
    </header>
  );
}

function InstallBanner({
  lang,
  onInstall,
  onDismiss,
}: {
  lang: Lang;
  onInstall: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="bg-pathways-50 border-b border-pathways-100 px-4 py-2">
      <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 text-sm">
        <span className="text-pathways-900">{t("install_hint", lang)}</span>
        <div className="flex items-center gap-2">
          <button
            onClick={onInstall}
            className="rounded-lg bg-pathways-700 px-3 py-1 text-white font-medium hover:bg-pathways-900"
          >
            {t("install_app", lang)}
          </button>
          <button
            onClick={onDismiss}
            className="text-pathways-900 text-xs hover:underline"
          >
            {t("install_later", lang)}
          </button>
        </div>
      </div>
    </div>
  );
}

function StageBar({ text }: { text: string }) {
  return (
    <div className="bg-amber-50 border-b border-amber-200 px-4 py-1 text-center text-xs text-amber-900">
      {text}
    </div>
  );
}

function TypingIndicator({ lang }: { lang: Lang }) {
  return (
    <div className="self-start text-xs text-slate-500 italic">
      {t("sending", lang)}
    </div>
  );
}

function BubbleView({ bubble, lang }: { bubble: Bubble; lang: Lang }) {
  if (bubble.kind === "user") {
    return (
      <div className="self-end max-w-[85%] rounded-2xl rounded-br-md bg-pathways-700 px-4 py-2 text-white shadow-sm whitespace-pre-wrap">
        {bubble.text}
      </div>
    );
  }
  if (bubble.kind === "error") {
    return (
      <div className="self-stretch rounded-xl bg-rose-50 border border-rose-200 px-4 py-2 text-sm text-rose-900">
        {bubble.text}
      </div>
    );
  }
  if (bubble.kind === "stage") {
    return null;
  }
  // bot
  return (
    <div className="self-start max-w-[92%] space-y-2">
      <div
        className="rounded-2xl rounded-bl-md bg-white border border-slate-200 px-4 py-3 text-slate-900 shadow-sm whitespace-pre-wrap"
        lang={bubble.lang}
      >
        {bubble.text}
      </div>
      {bubble.resources.length > 0 && (
        <div className="space-y-2">
          {bubble.resources.map((r) => (
            <ResourceCardView key={r.id} card={r} lang={lang} />
          ))}
        </div>
      )}
    </div>
  );
}

function ResourceCardView({ card, lang }: { card: ResourceCard; lang: Lang }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-slate-900 truncate">
            {card.name}
          </div>
          {card.distance_miles !== null && card.distance_miles !== undefined && (
            <div className="text-xs text-slate-500">
              ~{Math.round(card.distance_miles)} mi
            </div>
          )}
        </div>
        {card.category && (
          <span className="shrink-0 rounded-full bg-pathways-100 px-2 py-0.5 text-xs font-medium text-pathways-700">
            {card.category}
          </span>
        )}
      </div>
      {card.description && (
        <p className="mt-1 text-sm text-slate-700 line-clamp-3">
          {card.description}
        </p>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        {card.phone && (
          <a
            href={`tel:${card.phone.replace(/[^\d+]/g, "")}`}
            className="inline-flex items-center gap-1 rounded-lg bg-pathways-700 px-3 py-1 text-xs font-medium text-white hover:bg-pathways-900"
          >
            {t("call", lang)} {card.phone}
          </a>
        )}
        {card.url && (
          <a
            href={card.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >
            {t("visit", lang)}
          </a>
        )}
      </div>
    </div>
  );
}
