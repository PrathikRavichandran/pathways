import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { type Lang, t } from "../i18n";
import { AboutPage } from "../pages/AboutPage";
import { LearnPage } from "../pages/LearnPage";
import { EmergencyPage } from "../pages/EmergencyPage";
import { PrivacyPage } from "../pages/PrivacyPage";

export type MenuPage = "about" | "learn" | "emergency" | "privacy" | null;

// ---------------------------------------------------------------------------
// Hamburger trigger
// ---------------------------------------------------------------------------

export function MenuButton({
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
      aria-label={t("menu_open", lang)}
      whileHover={reduce ? undefined : { scale: 1.06 }}
      whileTap={reduce ? undefined : { scale: 0.94 }}
      transition={{ type: "spring", stiffness: 400, damping: 22 }}
      className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-cream-300 bg-cream-50/80 text-ink-600 transition hover:border-forest-400 hover:text-forest-700 dark:border-ink-700 dark:bg-ink-800/60 dark:text-cream-200 dark:hover:border-forest-400 dark:hover:text-forest-300"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M4 7h16M4 12h16M4 17h16"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
      </svg>
    </motion.button>
  );
}

// ---------------------------------------------------------------------------
// Drawer that lists the four pages
// ---------------------------------------------------------------------------

const ITEMS: { key: NonNullable<MenuPage>; labelKey: keyof typeof import("../i18n").T; emoji?: string }[] = [
  { key: "about", labelKey: "menu_about" },
  { key: "learn", labelKey: "menu_learn" },
  { key: "emergency", labelKey: "menu_emergency" },
  { key: "privacy", labelKey: "menu_privacy" },
];

export function MenuDrawer({
  open,
  lang,
  onClose,
  onSelect,
}: {
  open: boolean;
  lang: Lang;
  onClose: () => void;
  onSelect: (page: NonNullable<MenuPage>) => void;
}) {
  const reduce = useReducedMotion();
  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduce ? 0 : 0.15 }}
            className="fixed inset-0 z-40 bg-ink-700/30 backdrop-blur-sm dark:bg-ink-900/60"
            onClick={onClose}
          />
          {/* Drawer */}
          <motion.aside
            initial={reduce ? false : { x: "100%", opacity: 0 }}
            animate={reduce ? false : { x: 0, opacity: 1 }}
            exit={reduce ? undefined : { x: "100%", opacity: 0 }}
            transition={{ type: "spring", stiffness: 320, damping: 30 }}
            className="pt-safe pb-safe fixed inset-y-0 right-0 z-50 flex w-full max-w-sm flex-col border-l border-cream-300 bg-cream-50 shadow-lift dark:border-ink-700 dark:bg-ink-900"
            role="dialog"
            aria-modal="true"
          >
            <div className="flex items-center justify-between border-b border-cream-200 px-5 py-4 dark:border-ink-700">
              <span className="font-display text-lg font-semibold text-ink-700 dark:text-cream-100">
                {lang === "es" ? "Menú" : "Menu"}
              </span>
              <button
                onClick={onClose}
                aria-label={t("menu_close", lang)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-full text-ink-500 transition hover:bg-cream-200 hover:text-ink-700 dark:text-cream-400 dark:hover:bg-ink-800 dark:hover:text-cream-100"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M6 6l12 12M6 18L18 6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
                </svg>
              </button>
            </div>
            <nav className="flex-1 overflow-y-auto p-3">
              <ul className="space-y-1">
                {ITEMS.map((item) => (
                  <li key={item.key}>
                    <button
                      onClick={() => onSelect(item.key)}
                      className="group flex w-full items-center justify-between rounded-2xl px-4 py-3 text-left text-base font-medium text-ink-700 transition hover:bg-cream-200/70 dark:text-cream-100 dark:hover:bg-ink-800"
                    >
                      <span>{t(item.labelKey, lang)}</span>
                      <span
                        aria-hidden
                        className="text-ink-400 transition-transform group-hover:translate-x-0.5 dark:text-cream-400"
                      >
                        →
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </nav>
            <div className="border-t border-cream-200 px-5 py-3 text-center text-xs text-ink-400 dark:border-ink-700 dark:text-cream-400">
              {t("about", lang)}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

// ---------------------------------------------------------------------------
// Page overlay: full-screen page rendered over the chat
// ---------------------------------------------------------------------------

export function PageOverlay({
  page,
  lang,
  onClose,
}: {
  page: MenuPage;
  lang: Lang;
  onClose: () => void;
}) {
  const reduce = useReducedMotion();
  return (
    <AnimatePresence>
      {page !== null && (
        <motion.section
          initial={reduce ? false : { opacity: 0, y: 16 }}
          animate={reduce ? false : { opacity: 1, y: 0 }}
          exit={reduce ? undefined : { opacity: 0, y: 16 }}
          transition={{ duration: reduce ? 0 : 0.24, ease: [0.16, 1, 0.3, 1] }}
          className="bg-warmth pt-safe pb-safe fixed inset-0 z-30 flex flex-col"
          role="dialog"
          aria-modal="true"
        >
          <div className="sticky top-0 z-10 border-b border-cream-200/70 bg-cream-50/85 backdrop-blur-md dark:border-ink-700 dark:bg-ink-900/85">
            <div className="mx-auto flex max-w-2xl items-center justify-between px-4 py-3">
              <button
                onClick={onClose}
                className="inline-flex items-center gap-1.5 rounded-full border border-cream-300 px-3 py-1.5 text-xs font-semibold text-ink-600 transition hover:border-forest-400 hover:text-forest-700 dark:border-ink-700 dark:text-cream-200 dark:hover:border-forest-400 dark:hover:text-forest-300"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M15 18l-6-6 6-6"
                    stroke="currentColor"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                {t("back_to_chat", lang)}
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto px-5 py-6 pb-12">
            <div className="mx-auto max-w-2xl">
              {page === "about" && <AboutPage lang={lang} />}
              {page === "learn" && <LearnPage lang={lang} />}
              {page === "emergency" && <EmergencyPage lang={lang} />}
              {page === "privacy" && <PrivacyPage lang={lang} />}
            </div>
          </div>
        </motion.section>
      )}
    </AnimatePresence>
  );
}
