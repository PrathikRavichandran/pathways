# Pathways PWA

Installable Progressive Web App that shares the same FastAPI + LangGraph
backend as the SMS channel. Built with Vite + React 19 + TypeScript +
Tailwind + `vite-plugin-pwa`.

## Why a PWA and not native iOS / Android?

- One codebase serves both platforms (Add to Home Screen on iOS 16.4+
  and Android Chrome).
- Apple Developer Program is $99/year recurring; that violates the
  Pathways zero-spend constraint.
- ~90% of native UX is achievable as a PWA (offline cache, push, install,
  full-screen launch, share targets). The remaining 10% (deep camera,
  payment kits, true background tasks) is not needed for a reentry
  navigator.
- If real user demand ever justifies native, the same React code wraps
  cleanly with Capacitor and ships to the App Store + Play Store.

## Local development

```bash
cd web
cp .env.example .env.local       # then point VITE_API_URL at your backend
npm install
npm run dev                       # http://localhost:5173
```

In a second terminal, run the backend so the PWA has something to talk to:

```bash
cd ..
PATHWAYS_CHECKPOINT_BACKEND=memory \
PATHWAYS_THREAD_SALT=local-dev-only \
PATHWAYS_WEB_ALLOWED_ORIGINS=http://localhost:5173 \
uvicorn pathways.api.main:api --reload --port 7860
```

## Production build

```bash
npm run build
npm run preview                   # smoke-test the built bundle
```

## Deploy to Vercel

Same workflow as PropAI and Recrux frontend:

1. Go to <https://vercel.com/new>, import this repo.
2. Set **Root Directory** to `web`.
3. Framework preset auto-detects as Vite. Build command + output dir are
   already configured in `vercel.json`.
4. Add the env var: `VITE_API_URL` = your HF Space URL
   (e.g. `https://prathik10-pathways.hf.space`).
5. Deploy.
6. After first deploy, copy the Vercel URL and set it as the
   `PATHWAYS_WEB_ALLOWED_ORIGINS` secret on the HF Space so CORS lets
   the PWA call the backend.

## Install on a phone

- **iOS Safari**: tap the Share button, then "Add to Home Screen".
- **Android Chrome**: tap the install prompt that appears, or the
  three-dot menu's "Install app".

The PWA caches the app shell + the most recent `/web/turn` responses so
a user can open the app offline and see their last conversation.
