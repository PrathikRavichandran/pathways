import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// Pathways PWA Vite config. The PWA plugin generates manifest.webmanifest +
// service worker at build time. Icons live in /public/icons.
//
// Backend URL is provided via VITE_API_URL at build time. Defaults to the
// HF Space; override via .env.local for local dev.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    plugins: [
      react(),
      VitePWA({
        registerType: "autoUpdate",
        injectRegister: "auto",
        manifest: {
          name: "Pathways: TX Reentry Navigator",
          short_name: "Pathways",
          description:
            "Conversational navigator for people leaving incarceration in Texas. Housing, food, work, ID, benefits, legal aid.",
          theme_color: "#0D5C4F",
          background_color: "#FAF7F2",
          display: "standalone",
          orientation: "portrait",
          scope: "/",
          start_url: "/",
          lang: env.VITE_DEFAULT_LANGUAGE || "en",
          categories: ["social", "lifestyle", "utilities"],
          icons: [
            {
              src: "/icons/icon-192.png",
              sizes: "192x192",
              type: "image/png",
              purpose: "any maskable",
            },
            {
              src: "/icons/icon-512.png",
              sizes: "512x512",
              type: "image/png",
              purpose: "any maskable",
            },
            {
              src: "/icons/apple-touch-icon.png",
              sizes: "180x180",
              type: "image/png",
              purpose: "any",
            },
          ],
        },
        workbox: {
          // Cache the app shell + the latest sessions response so the user
          // can reopen the app offline and see their last conversation.
          runtimeCaching: [
            {
              urlPattern: /^https?:\/\/[^/]+\/web\/turn$/,
              handler: "NetworkFirst",
              options: {
                cacheName: "pathways-turn-cache",
                expiration: {
                  maxEntries: 50,
                  maxAgeSeconds: 60 * 60 * 24,
                },
              },
            },
          ],
        },
      }),
    ],
    server: {
      port: 5173,
      host: "0.0.0.0",
    },
    build: {
      sourcemap: true,
    },
  };
});
