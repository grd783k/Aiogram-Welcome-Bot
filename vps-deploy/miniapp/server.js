#!/usr/bin/env node
/**
 * Guardiola Farm 66 — Mini App server (standalone, no workspace deps)
 * Sert la Mini App Telegram à /api/ et expose /api/healthz
 * Compatible Node.js 18+
 */
"use strict";

const express = require("express");
const path    = require("path");
const fs      = require("fs");

const PORT       = parseInt(process.env.PORT || "8080", 10);
const PUBLIC_DIR = path.join(__dirname, "public");

if (!fs.existsSync(PUBLIC_DIR)) {
  console.error(`[miniapp] ERREUR : dossier public/ introuvable → ${PUBLIC_DIR}`);
  process.exit(1);
}

const app = express();

// ── Santé ─────────────────────────────────────────────────────────────────────
app.get("/api/healthz", (_req, res) => {
  res.json({ status: "ok", ts: new Date().toISOString() });
});

// ── Mini App — no-cache pour index.html ───────────────────────────────────────
app.use("/api", (req, res, next) => {
  if (req.path === "/" || req.path === "/index.html" || req.path === "") {
    res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate");
    res.setHeader("Pragma", "no-cache");
    res.setHeader("Expires", "0");
  }
  next();
});
app.use("/api", express.static(PUBLIC_DIR));

// ── Fallback SPA ──────────────────────────────────────────────────────────────
app.use((_req, res) => {
  res.sendFile(path.join(PUBLIC_DIR, "index.html"));
});

// ── Démarrage ─────────────────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`[miniapp] Serveur démarré sur le port ${PORT}`);
  console.log(`[miniapp] Mini App : http://localhost:${PORT}/api/`);
  console.log(`[miniapp] Health   : http://localhost:${PORT}/api/healthz`);
});

process.on("SIGTERM", () => { console.log("[miniapp] SIGTERM reçu, arrêt propre."); process.exit(0); });
process.on("SIGINT",  () => { console.log("[miniapp] SIGINT reçu, arrêt propre.");  process.exit(0); });
