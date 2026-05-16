import { forwardRef, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  getOrCreateSession,
  resetSession,
  sendTurn,
  type ResourceCard,
  type TurnResponse,
} from "./api";
import { type Lang, stageHint, t } from "./i18n";
import { LogoMark, LogoMarkOnSurface, Wordmark } from "./Logo";
import { MenuButton, MenuDrawer, PageOverlay, type MenuPage } from "./components/Menu";

type Bubble =
  | { kind: "user"; text: string; ts: number }
  | { kind: "bot"; text: string; resources: ResourceCard[]; lang: Lang; ts: number }
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
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [hasStarted, setHasStarted] = useState<boolean>(() => {
    return localStorage.getItem("pathways.started") === "true";
  });
  const install = useInstallPrompt();
  const threadRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [activePage, setActivePage] = useState<MenuPage>(null);

  // Auto-scroll on new bubble
  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTo({
        top: threadRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [bubbles, sending]);

  // Scroll the chat to the bottom when the visible viewport resizes (the
  // soft keyboard opening or closing on mobile triggers this). Keeps the
  // bot's most recent question pinned just above the composer instead of
  // hidden behind the keyboard.
  useEffect(() => {
    if (typeof window === "undefined" || !window.visualViewport) return;
    const vv = window.visualViewport;
    const onResize = () => {
      requestAnimationFrame(() => {
        if (threadRef.current) {
          threadRef.current.scrollTo({
            top: threadRef.current.scrollHeight,
            behavior: "smooth",
          });
        }
      });
    };
    vv.addEventListener("resize", onResize);
    return () => vv.removeEventListener("resize", onResize);
  }, []);

  // Same scroll when the composer gains focus (covers browsers where the
  // visualViewport resize event fires too late or not at all on focus).
  const scrollThreadToBottom = () => {
    setTimeout(() => {
      if (threadRef.current) {
        threadRef.current.scrollTo({
          top: threadRef.current.scrollHeight,
          behavior: "smooth",
        });
      }
    }, 250);
  };

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
      } catch {
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

  async function sendMessage(text: string) {
    if (!text.trim() || sending || !sessionId) return;
    if (!hasStarted) {
      setHasStarted(true);
      localStorage.setItem("pathways.started", "true");
    }
    const userBubble: Bubble = { kind: "user", text: text.trim(), ts: Date.now() };
    setBubbles((prev) => [...prev, userBubble]);
    setInput("");
    setSending(true);
    try {
      const resp: TurnResponse = await sendTurn(sessionId, text.trim());
      const botBubble: Bubble = {
        kind: "bot",
        text: resp.reply || "...",
        resources: resp.resources || [],
        lang: resp.language,
        ts: Date.now(),
      };
      setBubbles((prev) => [...prev, botBubble]);
      setStage(resp.intake_stage);
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

  function onSend() {
    sendMessage(input);
  }

  function onReset() {
    if (!confirm(t("reset_confirm", lang))) return;
    resetSession();
    localStorage.removeItem("pathways.started");
    setSessionId(null);
    setBubbles([]);
    setStage(null);
    setHasStarted(false);
    getOrCreateSession(lang).then((s) => setSessionId(s.session_id));
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  }

  function startFromWelcome(seedText?: string) {
    setHasStarted(true);
    localStorage.setItem("pathways.started", "true");
    if (seedText) {
      sendMessage(seedText);
    } else {
      // Focus the composer for a fresh start with no seed
      setTimeout(() => composerRef.current?.focus(), 50);
    }
  }

  const stageMsg = stageHint(stage, lang);

  return (
    <div className="flex h-full flex-col bg-warmth text-ink-700 dark:text-cream-100">
      <Header
        lang={lang}
        onToggleLang={() => setLang(lang === "en" ? "es" : "en")}
        onReset={onReset}
        showReset={hasStarted}
        onOpenMenu={() => setMenuOpen(true)}
      />

      <MenuDrawer
        open={menuOpen}
        lang={lang}
        onClose={() => setMenuOpen(false)}
        onSelect={(p) => {
          setMenuOpen(false);
          setActivePage(p);
        }}
      />
      <PageOverlay
        page={activePage}
        lang={lang}
        onClose={() => setActivePage(null)}
      />

      <AnimatePresence>
        {install.canInstall && (
          <InstallBanner
            lang={lang}
            onInstall={install.install}
            onDismiss={install.dismiss}
          />
        )}
      </AnimatePresence>

      {hasStarted && stageMsg && <StageBar text={stageMsg} />}

      {!hasStarted ? (
        <WelcomeScreen lang={lang} onStart={startFromWelcome} />
      ) : (
        <ChatThread
          bubbles={bubbles}
          sending={sending}
          lang={lang}
          threadRef={threadRef}
        />
      )}

      {hasStarted && (
        <Composer
          ref={composerRef}
          value={input}
          onChange={setInput}
          onSend={onSend}
          onKeyDown={onKeyDown}
          onFocus={scrollThreadToBottom}
          disabled={!sessionId || sending}
          sending={sending}
          lang={lang}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Welcome screen
// ---------------------------------------------------------------------------

function WelcomeScreen({
  lang,
  onStart,
}: {
  lang: Lang;
  onStart: (seedText?: string) => void;
}) {
  const reduce = useReducedMotion();
  const quickPrompts: { key: string; text: string }[] = [
    { key: "housing", text: t("quick_housing", lang) },
    { key: "food", text: t("quick_food", lang) },
    { key: "work", text: t("quick_work", lang) },
    { key: "id", text: t("quick_id", lang) },
  ];

  const fadeIn = (delay = 0) =>
    reduce
      ? { initial: false, animate: false as const }
      : {
          initial: { opacity: 0, y: 12 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1], delay },
        };

  return (
    <main className="flex-1 overflow-y-auto px-5 py-6 pb-10">
      <div className="mx-auto flex max-w-xl flex-col items-center text-center">
        <motion.div
          {...fadeIn(0)}
          className="mt-4 mb-6 rounded-3xl bg-cream-50/60 p-3 shadow-soft dark:bg-ink-800/40"
        >
          <LogoMark size={240} withGlow />
        </motion.div>
        <motion.p
          {...fadeIn(0.05)}
          className="text-xs font-medium uppercase tracking-[0.18em] text-forest-600 dark:text-forest-300"
        >
          {t("welcome_eyebrow", lang)}
        </motion.p>
        <motion.h1
          {...fadeIn(0.1)}
          className="mt-3 font-display text-3xl font-semibold leading-tight text-ink-700 sm:text-4xl dark:text-cream-100"
        >
          {t("welcome_title", lang)}
        </motion.h1>
        <motion.p
          {...fadeIn(0.18)}
          className="mt-4 max-w-md text-base leading-relaxed text-ink-500 dark:text-cream-300"
        >
          {t("welcome_body", lang)}
        </motion.p>

        <motion.div
          {...fadeIn(0.28)}
          className="mt-7 flex w-full flex-col gap-3 sm:max-w-sm"
        >
          <button
            onClick={() => onStart()}
            className="group inline-flex items-center justify-center gap-2 rounded-2xl bg-forest-600 px-6 py-3.5 text-base font-semibold text-cream-50 shadow-lift transition hover:bg-forest-700 active:translate-y-px dark:bg-forest-500 dark:hover:bg-forest-400"
          >
            {t("welcome_cta", lang)}
            <span
              aria-hidden
              className="transition-transform group-hover:translate-x-0.5"
            >
              →
            </span>
          </button>
        </motion.div>

        <motion.div {...fadeIn(0.36)} className="mt-8 w-full">
          <div className="mb-3 text-xs font-medium uppercase tracking-wider text-ink-400 dark:text-cream-400">
            {lang === "en" ? "Or jump straight to:" : "O salta directo a:"}
          </div>
          <div className="flex flex-wrap justify-center gap-2">
            {quickPrompts.map((q) => (
              <button
                key={q.key}
                onClick={() => onStart(q.text)}
                className="rounded-full border border-cream-300 bg-cream-50/80 px-4 py-2 text-sm font-medium text-ink-600 shadow-soft transition hover:border-forest-400 hover:bg-cream-50 hover:text-forest-700 dark:border-ink-600 dark:bg-ink-800/60 dark:text-cream-200 dark:hover:border-forest-400 dark:hover:text-forest-300"
              >
                {q.text}
              </button>
            ))}
          </div>
        </motion.div>

        <motion.p
          {...fadeIn(0.5)}
          className="mt-10 text-xs text-ink-400 dark:text-cream-400"
        >
          {t("privacy_note", lang)}
        </motion.p>
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Chat thread
// ---------------------------------------------------------------------------

function ChatThread({
  bubbles,
  sending,
  lang,
  threadRef,
}: {
  bubbles: Bubble[];
  sending: boolean;
  lang: Lang;
  threadRef: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <main
      ref={threadRef}
      className="chat-thread flex-1 overflow-y-auto px-4 py-5 pb-40"
    >
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        {bubbles.length === 0 && <FirstTurnBubble lang={lang} />}
        <AnimatePresence initial={false}>
          {bubbles.map((b, i) => (
            <BubbleView key={i} bubble={b} lang={lang} />
          ))}
        </AnimatePresence>
        {sending && <TypingIndicator />}
      </div>
    </main>
  );
}

function FirstTurnBubble({ lang }: { lang: Lang }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.36, ease: [0.16, 1, 0.3, 1] }}
      className="self-start max-w-[92%] rounded-3xl rounded-bl-md border border-cream-200 bg-cream-50 px-4 py-3 text-ink-700 shadow-soft dark:border-ink-700 dark:bg-ink-800 dark:text-cream-100"
    >
      {t("intent_greeting", lang)}
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Composer (sticky bottom)
// ---------------------------------------------------------------------------

type ComposerProps = {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onFocus?: () => void;
  disabled: boolean;
  sending: boolean;
  lang: Lang;
};

const Composer = forwardRef<HTMLTextAreaElement, ComposerProps>(function Composer(
  { value, onChange, onSend, onKeyDown, onFocus, disabled, sending, lang },
  ref,
) {
  return (
    <footer className="pb-safe fixed inset-x-0 bottom-0 z-20 border-t border-cream-200/80 bg-cream-50/85 backdrop-blur-md dark:border-ink-700 dark:bg-ink-900/85">
      <div className="mx-auto flex max-w-2xl items-end gap-2 px-3 pb-3 pt-3 sm:px-4">
        <div className="flex-1 rounded-3xl border border-cream-300 bg-cream-50 px-4 py-2 shadow-soft transition focus-within:border-forest-500 focus-within:ring-4 focus-within:ring-forest-500/15 dark:border-ink-700 dark:bg-ink-800">
          <textarea
            ref={ref}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            onFocus={onFocus}
            placeholder={t("input_placeholder", lang)}
            rows={1}
            disabled={disabled}
            className="block w-full resize-none bg-transparent text-base text-ink-700 outline-none placeholder:text-ink-400 disabled:opacity-60 dark:text-cream-100 dark:placeholder:text-cream-400"
            style={{
              maxHeight: "8rem",
              minHeight: "1.5rem",
            }}
            onInput={(e) => {
              const ta = e.currentTarget;
              ta.style.height = "auto";
              ta.style.height = Math.min(ta.scrollHeight, 128) + "px";
            }}
          />
        </div>
        <button
          onClick={onSend}
          disabled={disabled || !value.trim()}
          aria-label={t("send", lang)}
          className="shrink-0 inline-flex h-12 w-12 items-center justify-center rounded-full bg-forest-600 text-cream-50 shadow-lift transition hover:bg-forest-700 active:scale-95 disabled:cursor-not-allowed disabled:bg-cream-300 disabled:text-ink-300 dark:bg-forest-500 dark:hover:bg-forest-400 dark:disabled:bg-ink-700 dark:disabled:text-ink-400"
        >
          {sending ? <Spinner /> : <ArrowUp />}
        </button>
      </div>
      <p className="mb-2 mx-auto max-w-2xl px-4 text-center text-[11px] text-ink-400 dark:text-cream-400">
        {t("about", lang)}
      </p>
    </footer>
  );
});

function ArrowUp() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
      <path
        d="M12 19V5M12 5l-6 6M12 5l6 6"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Spinner() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      className="animate-spin"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeOpacity="0.25"
        strokeWidth="2.4"
      />
      <path
        d="M21 12a9 9 0 0 1-9 9"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Header({
  lang,
  onToggleLang,
  onReset,
  showReset,
  onOpenMenu,
}: {
  lang: Lang;
  onToggleLang: () => void;
  onReset: () => void;
  showReset: boolean;
  onOpenMenu: () => void;
}) {
  return (
    <header className="pt-safe sticky top-0 z-30 border-b border-cream-200/70 bg-cream-50/85 backdrop-blur-md dark:border-ink-700 dark:bg-ink-900/85">
      <div className="mx-auto flex max-w-2xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="text-forest-600 dark:text-forest-300">
            <LogoMarkOnSurface size={80} />
          </span>
          <Wordmark className="text-ink-700 dark:text-cream-100" />
        </div>
        <div className="flex items-center gap-2">
          <LangToggle lang={lang} onToggle={onToggleLang} />
          <AnimatePresence initial={false}>
            {showReset && <NewChatButton lang={lang} onClick={onReset} />}
          </AnimatePresence>
          <MenuButton lang={lang} onClick={onOpenMenu} />
        </div>
      </div>
    </header>
  );
}

function LangToggle({
  lang,
  onToggle,
}: {
  lang: Lang;
  onToggle: () => void;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.button
      onClick={onToggle}
      aria-label="Toggle language"
      whileHover={reduce ? undefined : { scale: 1.06 }}
      whileTap={reduce ? undefined : { scale: 0.94 }}
      transition={{ type: "spring", stiffness: 400, damping: 22 }}
      className="relative inline-flex h-8 w-[68px] items-center rounded-full border border-cream-300 bg-cream-50/80 px-1 text-[11px] font-semibold uppercase tracking-wider text-ink-600 shadow-soft transition hover:border-forest-400 hover:text-forest-700 dark:border-ink-700 dark:bg-ink-800/60 dark:text-cream-200 dark:hover:border-forest-400 dark:hover:text-forest-300"
    >
      {/* Sliding pill indicator */}
      <motion.span
        layout
        transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 500, damping: 32 }}
        className={
          "absolute top-1 bottom-1 w-[30px] rounded-full bg-forest-600 dark:bg-forest-500 " +
          (lang === "en" ? "left-1" : "left-[35px]")
        }
      />
      <span
        className={
          "relative z-10 flex-1 text-center transition-colors " +
          (lang === "en" ? "text-cream-50" : "")
        }
      >
        EN
      </span>
      <span
        className={
          "relative z-10 flex-1 text-center transition-colors " +
          (lang === "es" ? "text-cream-50" : "")
        }
      >
        ES
      </span>
    </motion.button>
  );
}

function NewChatButton({
  lang,
  onClick,
}: {
  lang: Lang;
  onClick: () => void;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.button
      onClick={onClick}
      aria-label={t("reset", lang)}
      initial={reduce ? false : { opacity: 0, x: 8, scale: 0.9 }}
      animate={reduce ? false : { opacity: 1, x: 0, scale: 1 }}
      exit={reduce ? undefined : { opacity: 0, x: 8, scale: 0.9 }}
      whileHover={reduce ? undefined : { scale: 1.04, y: -1 }}
      whileTap={reduce ? undefined : { scale: 0.94 }}
      transition={{ type: "spring", stiffness: 400, damping: 22 }}
      className="group inline-flex h-8 items-center gap-1.5 rounded-full border border-cream-300 bg-cream-50/80 px-3 text-[11px] font-semibold uppercase tracking-wider text-ink-600 shadow-soft transition hover:border-forest-400 hover:bg-cream-50 hover:text-forest-700 dark:border-ink-700 dark:bg-ink-800/60 dark:text-cream-200 dark:hover:border-forest-400 dark:hover:text-forest-300"
    >
      <motion.span
        aria-hidden
        animate={reduce ? undefined : { rotate: [0, 0] }}
        whileHover={reduce ? undefined : { rotate: 90 }}
        transition={{ type: "spring", stiffness: 220, damping: 14 }}
        className="inline-flex"
      >
        <ComposeIcon />
      </motion.span>
      {t("reset", lang)}
    </motion.button>
  );
}

function ComposeIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
      <path
        d="M12 5v14M5 12h14"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
    </svg>
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
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.24 }}
      className="border-b border-marigold-200/60 bg-marigold-50/80 px-4 py-2 dark:border-marigold-700/40 dark:bg-ink-800/70"
    >
      <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 text-sm">
        <span className="text-ink-700 dark:text-cream-200">
          {t("install_hint", lang)}
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={onInstall}
            className="rounded-full bg-marigold-500 px-3 py-1.5 text-xs font-semibold text-cream-50 shadow-soft transition hover:bg-marigold-600"
          >
            {t("install_app", lang)}
          </button>
          <button
            onClick={onDismiss}
            className="text-xs text-ink-500 underline-offset-2 hover:underline dark:text-cream-300"
          >
            {t("install_later", lang)}
          </button>
        </div>
      </div>
    </motion.div>
  );
}

function StageBar({ text }: { text: string }) {
  return (
    <div className="border-b border-forest-200/40 bg-forest-50/60 px-4 py-1.5 text-center text-[11px] font-medium uppercase tracking-wider text-forest-700 dark:border-forest-800/40 dark:bg-ink-800/60 dark:text-forest-300">
      {text}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="self-start rounded-3xl rounded-bl-md border border-cream-200 bg-cream-50 px-4 py-3 shadow-soft dark:border-ink-700 dark:bg-ink-800">
      <span className="typing-dot" />
      <span className="typing-dot" />
      <span className="typing-dot" />
    </div>
  );
}

function BubbleView({ bubble, lang }: { bubble: Bubble; lang: Lang }) {
  if (bubble.kind === "user") {
    return (
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
        className="self-end max-w-[85%] whitespace-pre-wrap rounded-3xl rounded-br-md bg-forest-600 px-4 py-2.5 text-cream-50 shadow-lift dark:bg-forest-500"
      >
        {bubble.text}
      </motion.div>
    );
  }
  if (bubble.kind === "error") {
    return (
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.24 }}
        className="self-stretch rounded-2xl border border-marigold-300/70 bg-marigold-50 px-4 py-3 text-sm text-marigold-700 dark:border-marigold-700/50 dark:bg-marigold-700/15 dark:text-marigold-200"
      >
        {bubble.text}
      </motion.div>
    );
  }
  // bot
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.36, ease: [0.16, 1, 0.3, 1] }}
      className="self-start max-w-[92%] space-y-3"
    >
      <div
        className="whitespace-pre-wrap rounded-3xl rounded-bl-md border border-cream-200 bg-cream-50 px-4 py-3 text-ink-700 shadow-soft dark:border-ink-700 dark:bg-ink-800 dark:text-cream-100"
        lang={bubble.lang}
      >
        {bubble.text}
      </div>
      {bubble.resources.length > 0 && (
        <div className="space-y-2.5">
          {bubble.resources.map((r, i) => (
            <ResourceCardView key={r.id} card={r} lang={lang} index={i} />
          ))}
        </div>
      )}
    </motion.div>
  );
}

function ResourceCardView({
  card,
  lang,
  index,
}: {
  card: ResourceCard;
  lang: Lang;
  index: number;
}) {
  const reduce = useReducedMotion();
  const tel = useMemo(
    () => (card.phone ? card.phone.replace(/[^\d+]/g, "") : null),
    [card.phone],
  );
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={reduce ? false : { opacity: 1, y: 0 }}
      transition={{
        duration: 0.36,
        ease: [0.16, 1, 0.3, 1],
        delay: Math.min(index * 0.06, 0.3),
      }}
      className="overflow-hidden rounded-2xl border border-cream-200 bg-cream-50 shadow-soft transition hover:shadow-lift dark:border-ink-700 dark:bg-ink-800"
    >
      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-semibold leading-snug text-ink-700 dark:text-cream-100">
              {card.name}
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-ink-400 dark:text-cream-400">
              {card.distance_miles != null && (
                <span>~{Math.round(card.distance_miles)} mi</span>
              )}
              {card.category && (
                <>
                  {card.distance_miles != null && <span>·</span>}
                  <span className="capitalize">{card.category}</span>
                </>
              )}
            </div>
          </div>
        </div>
        {card.description && (
          <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-ink-500 dark:text-cream-300">
            {card.description}
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {tel && (
            <a
              href={`tel:${tel}`}
              className="inline-flex items-center gap-1.5 rounded-full bg-forest-600 px-3.5 py-1.5 text-xs font-semibold text-cream-50 shadow-soft transition hover:bg-forest-700 dark:bg-forest-500 dark:hover:bg-forest-400"
            >
              <PhoneIcon /> {card.phone}
            </a>
          )}
          {card.url && (
            <a
              href={card.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-full border border-cream-300 px-3.5 py-1.5 text-xs font-semibold text-ink-600 transition hover:border-forest-400 hover:text-forest-700 dark:border-ink-700 dark:text-cream-200 dark:hover:border-forest-400 dark:hover:text-forest-300"
            >
              <LinkIcon /> {t("visit", lang)}
            </a>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function PhoneIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
      <path
        d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function LinkIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
      <path
        d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.5 1.5M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.5-1.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
