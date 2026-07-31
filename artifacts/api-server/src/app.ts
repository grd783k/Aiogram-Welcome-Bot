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

app.use("/api", router);

// Serve the Telegram Mini App static files (splash screen + app shell)
// Mounted under /api because the Replit proxy forwards the full path without stripping the prefix.
const publicDir = path.join(__dirname, "../public");
app.use("/api", express.static(publicDir));

// SPA fallback: any unmatched route returns index.html (splash screen)
app.use((_req, res) => {
  res.sendFile(path.join(publicDir, "index.html"));
});

export default app;
