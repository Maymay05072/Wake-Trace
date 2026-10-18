import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { access, copyFile, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import worker from "../worker/index.js";

test("serves existing static assets without a fallback", async () => {
  const calls = [];
  const response = await worker.fetch(new Request("https://example.test/assets/app.js"), {
    ASSETS: {
      fetch: async (request) => {
        calls.push(new URL(request.url).pathname);
        return new Response("asset", { status: 200 });
      },
    },
  });

  assert.equal(response.status, 200);
  assert.deepEqual(calls, ["/assets/app.js"]);
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(response.headers.get("x-frame-options"), "DENY");
  assert.match(response.headers.get("content-security-policy"), /frame-ancestors 'none'/);
});

test("falls back to index.html for an unknown app route", async () => {
  const calls = [];
  const response = await worker.fetch(
    new Request("https://example.test/flow/step-two?source=share", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async (request) => {
          const url = new URL(request.url);
          calls.push(url.pathname + url.search);
          return new Response(url.pathname === "/index.html" ? "app" : "missing", {
            status: url.pathname === "/index.html" ? 200 : 404,
          });
        },
      },
    },
  );

  assert.equal(response.status, 200);
  assert.deepEqual(calls, ["/flow/step-two?source=share", "/index.html"]);
});

test("does not turn missing API or write requests into the app shell", async () => {
  for (const request of [
    new Request("https://example.test/api/missing", { headers: { accept: "application/json" } }),
    new Request("https://example.test/flow", { method: "POST", headers: { accept: "text/html" } }),
  ]) {
    let calls = 0;
    const response = await worker.fetch(request, {
      ASSETS: {
        fetch: async () => {
          calls += 1;
          return new Response("missing", { status: 404 });
        },
      },
    });

    assert.equal(response.status, 404);
    assert.equal(calls, 1);
  }
});

test("emits standalone Web and optional Sites files", async () => {
  await access(new URL("../dist/client/index.html", import.meta.url));
  if (existsSync(new URL("../.openai/hosting.json", import.meta.url))) {
    await access(new URL("../dist/server/index.js", import.meta.url));
    await access(new URL("../dist/.openai/hosting.json", import.meta.url));
  }
});

test("build preparation supports both public standalone and configured Sites projects", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "waketrace-build-"));
  try {
    await mkdir(path.join(root, "scripts"), { recursive: true });
    await mkdir(path.join(root, "dist/client"), { recursive: true });
    await mkdir(path.join(root, "worker"), { recursive: true });
    const script = path.join(root, "scripts/prepare-sites-build.mjs");
    await copyFile(new URL("../scripts/prepare-sites-build.mjs", import.meta.url), script);
    await writeFile(path.join(root, "dist/client/index.html"), "test app");
    await writeFile(path.join(root, "worker/index.js"), "export default {};");
    execFileSync(process.execPath, [script]);
    assert.equal(existsSync(path.join(root, "dist/server/index.js")), false);
    await mkdir(path.join(root, ".openai"));
    await writeFile(path.join(root, ".openai/hosting.json"), "{}");
    execFileSync(process.execPath, [script]);
    await access(path.join(root, "dist/server/index.js"));
    await access(path.join(root, "dist/.openai/hosting.json"));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

