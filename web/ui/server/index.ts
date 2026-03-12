import express, { type Request, Response, NextFunction } from "express";
import http from "http";
import { registerRoutes } from "./routes";
import { setupVite, serveStatic, log } from "./vite";

const app = express();

declare module 'http' {
  interface IncomingMessage {
    rawBody: unknown
  }
}

// Skip body parsing for proxied routes so Vite http-proxy can forward raw body
const PROXY_PREFIXES = ["/api", "/webrtc", "/hls"];
const isProxied = (p: string) => PROXY_PREFIXES.some((px) => p.startsWith(px));

app.use((req, res, next) => {
  if (isProxied(req.path)) return next();
  express.json({ verify: (r, _res, buf) => { (r as any).rawBody = buf; } })(req, res, next);
});
app.use((req, res, next) => {
  if (isProxied(req.path)) return next();
  express.urlencoded({ extended: false })(req, res, next);
});

// ── MediaMTX reverse proxy (crash-safe) ───────────────────────
// Handles /webrtc/* and /hls/* by proxying to MediaMTX.
// Returns 502 gracefully when MediaMTX is unavailable instead of crashing.
const MEDIAMTX_TARGETS: Record<string, { host: string; port: number }> = {
  "/webrtc": (() => {
    const u = new URL(process.env.VITE_MEDIAMTX_WEBRTC_TARGET || "http://127.0.0.1:8889");
    return { host: u.hostname, port: parseInt(u.port || "8889", 10) };
  })(),
  "/hls": (() => {
    const u = new URL(process.env.VITE_MEDIAMTX_HLS_TARGET || "http://127.0.0.1:8888");
    return { host: u.hostname, port: parseInt(u.port || "8888", 10) };
  })(),
};

for (const [prefix, target] of Object.entries(MEDIAMTX_TARGETS)) {
  app.use(prefix, (req: Request, res: Response) => {
    const targetPath = req.url; // already has prefix stripped by Express mount
    const proxyReq = http.request(
      {
        hostname: target.host,
        port: target.port,
        path: targetPath,
        method: req.method,
        headers: { ...req.headers, host: `${target.host}:${target.port}` },
      },
      (proxyRes) => {
        res.writeHead(proxyRes.statusCode ?? 502, proxyRes.headers);
        proxyRes.pipe(res, { end: true });
      },
    );
    proxyReq.on("error", (err: NodeJS.ErrnoException) => {
      log(`MediaMTX ${prefix} proxy unavailable: ${err.message}`);
      if (!res.headersSent) {
        res.writeHead(502, { "Content-Type": "text/plain" });
        res.end("MediaMTX unavailable");
      }
    });
    req.pipe(proxyReq, { end: true });
  });
}

app.use((req, res, next) => {
  const start = Date.now();
  const path = req.path;
  let capturedJsonResponse: Record<string, any> | undefined = undefined;

  const originalResJson = res.json;
  res.json = function (bodyJson, ...args) {
    capturedJsonResponse = bodyJson;
    return originalResJson.apply(res, [bodyJson, ...args]);
  };

  res.on("finish", () => {
    const duration = Date.now() - start;
    if (path.startsWith("/api")) {
      let logLine = `${req.method} ${path} ${res.statusCode} in ${duration}ms`;
      if (capturedJsonResponse) {
        logLine += ` :: ${JSON.stringify(capturedJsonResponse)}`;
      }

      if (logLine.length > 80) {
        logLine = logLine.slice(0, 79) + "…";
      }

      log(logLine);
    }
  });

  next();
});

(async () => {
  const server = await registerRoutes(app);

  app.use((err: any, _req: Request, res: Response, _next: NextFunction) => {
    const status = err.status || err.statusCode || 500;
    const message = err.message || "Internal Server Error";

    res.status(status).json({ message });
    throw err;
  });

  // importantly only setup vite in development and after
  // setting up all the other routes so the catch-all route
  // doesn't interfere with the other routes
  if (app.get("env") === "development") {
    await setupVite(app, server);
  } else {
    serveStatic(app);
  }

  // ALWAYS serve the app on the port specified in the environment variable PORT
  // Other ports are firewalled. Default to 5000 if not specified.
  // this serves both the API and the client.
  // It is the only port that is not firewalled.
  const port = parseInt(process.env.PORT || '5000', 10);
  server.listen({
    port,
    host: "0.0.0.0",
    reusePort: true,
  }, () => {
    log(`serving on port ${port}`);
  });
})();
