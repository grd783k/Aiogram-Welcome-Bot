import express, { type Express } from "express";
import cors from "cors";
import path from "path";
import { fileURLToPath } from "url";
import pinoHttp from "pino-http";
import router from "./routes";
import { logger } from "./lib/logger";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const app: Express = express();

app.use(
  pinoHttp({
    logger,
    serializers: {
      req(req) {
        return {
          id: req.id,
          method: req.method,
          url: req.url?.split("?")[0],
        };
      },
      res(res) {
        return {
          statusCode: res.statusCode,
        };
      },
    },
  }),
);
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Serve the Telegram Mini App static files FIRST so /api/ → index.html
// takes priority over the API router catch-all.
// index.html is served with no-cache so Telegram never serves a stale version.
const publicDir = path.join(__dirname, "../public");
app.use("/api", (req, res, next) => {
  if (req.path === "/" || req.path === "/index.html") {
    res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate");
    res.setHeader("Pragma", "no-cache");
    res.setHeader("Expires", "0");
  }
  next();
});
app.use("/api", express.static(publicDir));

// API routes (/api/healthz, etc.)
app.use("/api", router);

// SPA fallback: any unmatched route returns the splash screen
app.use((_req, res) => {
  res.sendFile(path.join(publicDir, "index.html"));
});

export default app;
