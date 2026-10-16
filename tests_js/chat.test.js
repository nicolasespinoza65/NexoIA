// Pruebas del chat flotante sin navegador: un DOM mínimo de mentira basta porque chat.js solo usa
// unas pocas funciones. Ejecutar con: node --test tests_js/chat.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "..", "static", "js", "chat.js"), "utf8");

class El {
  constructor(tag) {
    this.tag = tag; this.children = []; this.listeners = {}; this.dataset = {}; this.className = "";
    this.attrs = {}; this.hidden = false; this.textContent = ""; this.parent = null;
    this.scrollTop = 0; this.scrollHeight = 0; this.value = ""; this.disabled = false;
  }
  appendChild(c) { c.parent = this; this.children.push(c); return c; }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter((x) => x !== this); this.parent = null; } }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  click() { (this.listeners.click || []).forEach((f) => f({})); }
  submit() { (this.listeners.submit || []).forEach((f) => f({ preventDefault() {} })); }
  focus() {}
  querySelector(sel) { return (this._q || {})[sel] || new El("x"); }
  set innerHTML(_) {}
}

// Arma la página falsa y ejecuta chat.js. `respond(url, opts)` simula al servidor.
function setup({ auth, respond }) {
  const body = new El("div"), input = new El("input"), sendBtn = new El("button"), humanBtn = new El("button");
  const launcher = new El("button"), panel = new El("section"), closeBtn = new El("button");
  panel.hidden = true;
  const form = new El("form"); form._q = { ".chat-send": sendBtn };
  const root = new El("div");
  root.dataset = {
    auth: auth ? "1" : "0", csrf: "token", loginUrl: "/login/", registerUrl: "/registro/",
    sendUrl: "/asistente/enviar/", humanUrl: "/asistente/persona/", historyUrl: "/asistente/historial/", suggestionsUrl: "/asistente/visitante/",
  };
  root._q = { ".chat-launcher": launcher, ".chat-panel": panel, ".chat-close": closeBtn, ".chat-human": humanBtn };
  const document = {
    getElementById: (id) => ({ "chat-widget": root, "chat-body": body, "chat-form": form, "chat-input": input })[id],
    addEventListener() {}, createElement: (t) => new El(t), activeElement: null,
  };
  const fetch = (url, opts) => Promise.resolve(respond(url, opts));
  vm.runInNewContext(SOURCE, { document, fetch, JSON, Promise });
  return { body, input, launcher, form, humanBtn };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 15));
const json = (data, ok = true) => ({ ok, json: () => Promise.resolve(data), text: () => Promise.resolve(JSON.stringify(data)) });
const chipsOf = (body) => {
  const el = body.children.find((c) => c.className.includes("chips"));
  return el ? el.children.map((b) => b.textContent) : [];
};
const lastBot = (body) => body.children.filter((c) => c.className.includes("bot")).pop();

test("el visitante usa las 3 preguntas rápidas y luego se le invita a registrarse", async () => {
  const quick = ["P1", "P2", "P3"];
  const { body, launcher } = setup({
    auth: false,
    respond: (url, opts) => (opts && opts.method === "POST"
      ? json({ answer: "Respuesta a " + JSON.parse(opts.body).message, needs_account: false })
      : json({ suggestions: quick })),
  });
  launcher.click();
  await tick();
  assert.deepStrictEqual(chipsOf(body), ["P1", "P2", "P3"]);

  for (const [index, question] of quick.entries()) {
    body.children.find((c) => c.className.includes("chips")).children.find((b) => b.textContent === question).click();
    await tick();
    assert.strictEqual(chipsOf(body).length, quick.length - index - 1, "reaparecen solo las no usadas");
  }
  assert.match(lastBot(body).textContent, /preguntas rápidas/);
  assert.strictEqual(lastBot(body).children.filter((c) => c.tag === "a").length, 2, "enlaces a ingresar y crear cuenta");
});

test("si el servidor responde una página de error HTML, el usuario ve un mensaje amable", async () => {
  const { body, launcher, input, form } = setup({
    auth: false,
    respond: (url, opts) => (opts && opts.method === "POST"
      ? { ok: false, text: () => Promise.resolve("<!DOCTYPE html><h1>Server Error</h1>") }
      : json({ suggestions: [] })),
  });
  launcher.click();
  await tick();
  input.value = "hola";
  form.submit();
  await tick();
  assert.match(lastBot(body).textContent, /No pudimos enviar tu mensaje/);
  assert.doesNotMatch(lastBot(body).textContent, /DOCTYPE|Unexpected token/);
});

test("el cliente con historial lo ve y no recibe preguntas rápidas", async () => {
  const { body, launcher } = setup({
    auth: true,
    respond: () => json({ messages: [{ question: "hola", answer: "¡Hola!" }], suggestions: ["P1"] }),
  });
  launcher.click();
  await tick();
  assert.strictEqual(body.children.length, 2);
  assert.strictEqual(chipsOf(body).length, 0);
});

test("un mensaje con ticket creado muestra el enlace al ticket", async () => {
  const { body, launcher, input, form } = setup({
    auth: true,
    respond: (url, opts) => (opts && opts.method === "POST"
      ? json({ answer: "Creé el ticket #7", ticket_id: 7, ticket_url: "/tickets/7/" })
      : json({ messages: [], suggestions: [] })),
  });
  launcher.click();
  await tick();
  input.value = "se me quemó un enchufe";
  form.submit();
  await tick();
  const link = lastBot(body).children.find((c) => c.tag === "a");
  assert.strictEqual(link.href, "/tickets/7/");
  assert.match(link.textContent, /#7/);
});

test("«Hablar con una persona» crea la solicitud y muestra el enlace al ticket", async () => {
  const calls = [];
  const { body, launcher, humanBtn } = setup({
    auth: true,
    respond: (url, opts) => {
      calls.push(url);
      return opts && opts.method === "POST"
        ? json({ answer: "Listo, avisé a nuestro equipo (ticket #9).", ticket_id: 9, ticket_url: "/tickets/9/" })
        : json({ messages: [], suggestions: [] });
    },
  });
  launcher.click();
  await tick();
  humanBtn.click();
  await tick();
  assert.ok(calls.includes("/asistente/persona/"), "llama al endpoint de atención humana");
  const link = lastBot(body).children.find((c) => c.tag === "a");
  assert.strictEqual(link.href, "/tickets/9/");
});

test("sin cuenta, «Hablar con una persona» invita a ingresar y no llama al servidor", async () => {
  const posts = [];
  const { body, launcher, humanBtn } = setup({
    auth: false,
    respond: (url, opts) => {
      if (opts && opts.method === "POST") posts.push(url);
      return json({ suggestions: [] });
    },
  });
  launcher.click();
  await tick();
  humanBtn.click();
  await tick();
  assert.strictEqual(posts.length, 0);
  assert.strictEqual(lastBot(body).children.filter((c) => c.tag === "a").length, 2);
});

test("si «Hablar con una persona» falla, se muestra un mensaje amable", async () => {
  const { body, launcher, humanBtn } = setup({
    auth: true,
    respond: (url, opts) => (opts && opts.method === "POST"
      ? { ok: false, text: () => Promise.resolve("<html>500</html>") }
      : json({ messages: [], suggestions: [] })),
  });
  launcher.click();
  await tick();
  humanBtn.click();
  await tick();
  assert.match(lastBot(body).textContent, /No pudimos enviar tu mensaje/);
});
