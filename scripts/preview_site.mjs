// Local preview serves only the production allowlist, never the repo or licenses.
import { createServer } from "node:http";
import { createReadStream, readFileSync, statSync } from "node:fs";
import { resolve, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const option = (name, fallback) =>
  args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const port = Number(option("--port", "4173"));
const host = option("--host", "0.0.0.0");
const manifest = () =>
  new Set(
    readFileSync(resolve(root, "cloudflare/public-files.txt"), "utf8")
      .trim()
      .split(/\r?\n/),
  );
const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css",
  ".js": "text/javascript",
  ".jpg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".json": "application/json",
  ".txt": "text/plain",
};
const server = createServer((request, response) => {
  if (!["GET", "HEAD"].includes(request.method)) {
    response.writeHead(405).end();
    return;
  }
  let path;
  try {
    path = decodeURIComponent(
      new URL(request.url, "http://preview.invalid").pathname,
    ).replace(/^\//, "");
  } catch {
    response.writeHead(400).end();
    return;
  }
  if (!path) path = "index.html";
  // Explicit local-only viewport harness; not included in the deployment manifest.
  if (path === "__qa") {
    response.writeHead(200, {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    });
    response.end(readFileSync(resolve(root, "scripts/responsive_qa.html")));
    return;
  }
  if (
    [
      "affiliate",
      "affiliate/",
      "affiliate-dashboard",
      "affiliate-dashboard/",
    ].includes(path)
  )
    path = path.replace(/\/$/, "") + ".html";
  if (!manifest().has(path)) {
    response.writeHead(404, { "Content-Type": "text/plain" }).end("Not found");
    return;
  }
  const file = resolve(root, path);
  let size;
  try {
    size = statSync(file).size;
  } catch {
    response.writeHead(404).end();
    return;
  }
  const headers = {
    "Content-Type": types[extname(file)] || "application/octet-stream",
    "Cache-Control": "no-store",
    "Accept-Ranges": "bytes",
    "X-Content-Type-Options": "nosniff",
  };
  let start = 0,
    end = size - 1,
    status = 200;
  if (request.headers.range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(request.headers.range);
    if (!match || (!match[1] && !match[2])) {
      response.writeHead(416, { "Content-Range": `bytes */${size}` }).end();
      return;
    }
    if (!match[1]) start = Math.max(0, size - Number(match[2]));
    else {
      start = Number(match[1]);
      if (match[2]) end = Math.min(end, Number(match[2]));
    }
    if (start > end || start >= size) {
      response.writeHead(416, { "Content-Range": `bytes */${size}` }).end();
      return;
    }
    status = 206;
    headers["Content-Range"] = `bytes ${start}-${end}/${size}`;
  }
  headers["Content-Length"] = Math.max(0, end - start + 1);
  response.writeHead(status, headers);
  if (request.method === "HEAD" || size === 0) {
    response.end();
    return;
  }
  const stream = createReadStream(file, { start, end });
  stream.on("error", () => response.destroy());
  request.on("close", () => stream.destroy());
  stream.pipe(response);
});
server.on("error", (error) => {
  console.error(error.message);
  process.exit(1);
});
server.listen(port, host, () =>
  console.log(`PlugICT allowlisted preview ready on port ${server.address().port}`),
);
