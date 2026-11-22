// A tiny static file server for media/ (Chromium won't load fonts from file:// pages; videos need ranges).
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

export const MEDIA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const TYPES = {
  ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript",
  ".jpg": "image/jpeg", ".png": "image/png", ".webm": "video/webm", ".woff2": "font/woff2", ".svg": "image/svg+xml",
};

/** Serves MEDIA on 127.0.0.1:port (0 = any free port). Resolves to the http.Server. */
export function serve(port = 0) {
  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, "http://x");
      const file = path.join(MEDIA, decodeURIComponent(url.pathname));
      if (!file.startsWith(MEDIA)) throw new Error("outside");
      let info = await stat(file);
      let target = file;
      if (info.isDirectory()) {
        target = path.join(file, "index.html");
        info = await stat(target);
      }
      const type = TYPES[path.extname(target).toLowerCase()] ?? "application/octet-stream";
      const data = await readFile(target);
      const range = req.headers.range?.match(/bytes=(\d*)-(\d*)/);
      if (range) {
        const start = range[1] ? Number(range[1]) : 0;
        const end = range[2] ? Number(range[2]) : info.size - 1;
        res.writeHead(206, { "content-type": type, "content-range": `bytes ${start}-${end}/${info.size}`, "accept-ranges": "bytes", "content-length": end - start + 1 });
        res.end(data.subarray(start, end + 1));
      } else {
        res.writeHead(200, { "content-type": type, "accept-ranges": "bytes", "content-length": info.size });
        res.end(data);
      }
    } catch {
      res.writeHead(404).end();
    }
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}
