/** Production same-origin gateway. No inference or simulation runs in this process. */
import http from "node:http";
import https from "node:https";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { resolve, extname, sep } from "node:path";
import { createGzip } from "node:zlib";
const root = resolve(import.meta.dirname);
const upstream = new URL(
  process.env.UITA_SERVER_URL || "http://127.0.0.1:8001",
);
const types = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".glb": "model/gltf-binary",
  ".woff2": "font/woff2",
  ".wasm": "application/wasm",
};
const server = http.createServer(async (req, res) => {
  let url;
  try {
    url = new URL(req.url, "http://localhost");
    decodeURIComponent(url.pathname);
  } catch {
    res.writeHead(400);
    return res.end("Invalid URL");
  }
  // Private deployments delegate page authorization to the API server.
  if (
    process.env.UITA_ACCESS_MODE === "public_demo" &&
    ["GET", "HEAD"].includes(req.method)
  ) {
    let file;
    if (url.pathname === "/") file = resolve(root, "candidates/app.html");
    else if (["/sfo-overview", "/sfo-overview/"].includes(url.pathname))
      file = resolve(root, "candidates/sfo-overview.html");
    else
      for (const [prefix, dir] of [
        ["/candidates/", "candidates"],
        ["/vendor/cesium/", "node_modules/cesium/Build/Cesium"],
        ["/vendor/three/", "node_modules/three186"],
      ]) {
        if (url.pathname.startsWith(prefix)) {
          const base = resolve(root, dir);
          const candidate = resolve(
            base,
            decodeURIComponent(url.pathname.slice(prefix.length)),
          );
          if (candidate.startsWith(base + sep)) file = candidate;
          break;
        }
      }
    if (file)
      try {
        const s = await stat(file);
        if (!s.isFile()) throw Error();
        const tag = `"${s.size.toString(16)}-${Math.floor(s.mtimeMs).toString(16)}"`;
        res.setHeader("ETag", tag);
        res.setHeader("Vary", "Accept-Encoding");
        res.setHeader(
          "Cache-Control",
          /\.(html|js|css)$/.test(file) ? "no-cache" : "public, max-age=86400",
        );
        res.setHeader(
          "Content-Type",
          types[extname(file)] || "application/octet-stream",
        );
        res.setHeader("X-Content-Type-Options", "nosniff");
        res.setHeader("Content-Security-Policy", "frame-ancestors 'self'");
        if (req.headers["if-none-match"] === tag) {
          res.writeHead(304);
          return res.end();
        }
        if (req.method === "HEAD") return res.end();
        const stream = createReadStream(file);
        stream.on("error", () => res.destroy());
        if (
          /gzip/.test(req.headers["accept-encoding"] || "") &&
          /\.(js|css|html|json|svg|wasm)$/.test(file)
        ) {
          res.setHeader("Content-Encoding", "gzip");
          stream.pipe(createGzip()).pipe(res);
        } else stream.pipe(res);
        return;
      } catch {
        res.writeHead(404);
        return res.end("Asset not found");
      }
  }
  const target = new URL(upstream);
  target.pathname = url.pathname;
  target.search = url.search;
  const transport = target.protocol === "https:" ? https : http;
  const headers = {
    ...req.headers,
    host: upstream.host,
    "x-forwarded-host": req.headers.host,
    "x-forwarded-proto": req.headers["x-forwarded-proto"] || "https",
  };
  delete headers.connection;
  const request = transport.request(
    target,
    { method: req.method, headers },
    (response) => {
      res.writeHead(response.statusCode, response.headers);
      response.pipe(res);
    },
  );
  request.on("error", () => {
    if (!res.headersSent) {
      res.writeHead(502, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: "Research server unavailable" }));
    } else res.destroy();
  });
  res.on("close", () => request.destroy());
  req.pipe(request);
});
server.listen(Number(process.env.PORT || 5190), "0.0.0.0");
