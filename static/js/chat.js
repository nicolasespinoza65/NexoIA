/* Chat flotante del asistente.
   - Cliente con sesión: carga su historial y envía mensajes a /asistente/enviar/ (puede crear tickets).
   - Visitante sin cuenta: pregunta lo básico a /asistente/visitante/ (sin historial ni tickets);
     si su consulta necesita registro, el asistente le ofrece ingresar o crear una cuenta. */
(function () {
  var root = document.getElementById("chat-widget");
  if (!root) return;

  var launcher = root.querySelector(".chat-launcher");
  var panel = root.querySelector(".chat-panel");
  var closeBtn = root.querySelector(".chat-close");
  var body = document.getElementById("chat-body");
  var form = document.getElementById("chat-form");
  var input = document.getElementById("chat-input");
  var sendBtn = form.querySelector(".chat-send");
  var humanBtn = root.querySelector(".chat-human");
  var authed = root.dataset.auth === "1";
  var chips = null;
  var remaining = [];      // preguntas rápidas que todavía no se han usado
  var offeredQuick = false;
  var nudged = false;
  var started = false;
  var busy = false;
  var FRIENDLY_ERROR = "No pudimos enviar tu mensaje. Inténtalo de nuevo en un momento.";

  function scrollToEnd() {
    body.scrollTop = body.scrollHeight;
  }

  // links: lista opcional de {text, href} que se muestran dentro de la burbuja
  function addMessage(text, who, links) {
    var el = document.createElement("div");
    el.className = "chat-msg " + who;
    el.textContent = text;
    if (links && links.length) {
      el.appendChild(document.createElement("br"));
      links.forEach(function (l) {
        var a = document.createElement("a");
        a.href = l.href;
        a.textContent = l.text;
        el.appendChild(a);
      });
    }
    body.appendChild(el);
    scrollToEnd();
    return el;
  }

  function showTyping() {
    var el = document.createElement("div");
    el.className = "chat-msg bot chat-typing";
    el.setAttribute("aria-label", "El asistente está escribiendo");
    el.innerHTML = "<i></i><i></i><i></i>";
    body.appendChild(el);
    scrollToEnd();
    return el;
  }

  // Preguntas rápidas: tras cada respuesta vuelven a aparecer las que aún no se han usado
  function showSuggestions(items) {
    if (!items || !items.length) return;
    remaining = items.slice();
    offeredQuick = true;
    renderChips();
  }

  function renderChips() {
    clearChips();
    if (!remaining.length) return;
    chips = document.createElement("div");
    chips.className = "chat-chips";
    remaining.forEach(function (text) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "chat-chip";
      b.textContent = text;
      b.addEventListener("click", function () { sendMessage(text); });
      chips.appendChild(b);
    });
    body.appendChild(chips);
    scrollToEnd();
  }

  function clearChips() {
    if (chips) { chips.remove(); chips = null; }
  }

  function loadClientHistory() {
    fetch(root.dataset.historyUrl, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        if (!data.messages.length) {
          addMessage("Hola, soy el asistente de Soluciones SSDP. Pregúntame por nuestros servicios eléctricos o cómo pedir uno.", "bot");
          showSuggestions(data.suggestions);
          return;
        }
        data.messages.forEach(function (m) {
          addMessage(m.question, "user");
          addMessage(m.answer, "bot");
        });
      })
      .catch(function () {
        started = false;
        addMessage("No pudimos cargar tu historial. Cierra y vuelve a abrir el chat.", "bot");
      });
  }

  function loadGuestWelcome() {
    addMessage("Hola, soy el asistente de Soluciones SSDP. Puedes preguntarme lo básico sin cuenta; para registrar una solicitud necesitarás ingresar.", "bot");
    fetch(root.dataset.suggestionsUrl, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (data) { showSuggestions(data.suggestions); })
      .catch(function () {});
  }

  function open() {
    panel.hidden = false;
    launcher.setAttribute("aria-expanded", "true");
    if (!started) {
      started = true;
      if (authed) loadClientHistory(); else loadGuestWelcome();
    }
    input.focus();
  }

  function close() {
    panel.hidden = true;
    launcher.setAttribute("aria-expanded", "false");
    launcher.focus();
  }

  // Envía JSON y devuelve {ok, data}. Si el servidor responde algo que no es JSON (por ejemplo una página de
  // error), no se muestra al usuario: data queda vacío y ok en falso.
  function postJson(url, payload) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": root.dataset.csrf },
      body: JSON.stringify(payload)
    }).then(function (r) {
      return r.text().then(function (raw) {
        var data = null;
        try { data = JSON.parse(raw); } catch (e) { data = null; }
        return { ok: r.ok && data !== null, data: data || {} };
      });
    });
  }

  function accountLinks() {
    return [
      { text: "Ingresar", href: root.dataset.loginUrl },
      { text: "Crear cuenta", href: root.dataset.registerUrl }
    ];
  }

  // «Hablar con una persona»: crea un ticket para que un moderador responda
  function askForHuman() {
    if (busy) return;
    if (!authed) {
      addMessage("Para que una persona te responda necesito registrar tu consulta: ingresa o crea una cuenta.", "bot", accountLinks());
      return;
    }
    busy = true;
    clearChips();
    addMessage("Quiero hablar con una persona", "user");
    var typing = showTyping();
    postJson(root.dataset.humanUrl, {})
      .then(function (res) {
        typing.remove();
        if (!res.ok) throw new Error();
        addMessage(res.data.answer, "bot", res.data.ticket_url ? [{ text: "Ver ticket #" + res.data.ticket_id, href: res.data.ticket_url }] : []);
      })
      .catch(function () {
        typing.remove();
        addMessage(FRIENDLY_ERROR, "bot");
      })
      .then(function () {
        busy = false;
        renderChips();
      });
  }

  function sendMessage(text) {
    text = (text || "").trim();
    if (!text || busy) return;

    busy = true;
    sendBtn.disabled = true;
    input.value = "";
    clearChips();
    remaining = remaining.filter(function (t) { return t !== text; });
    addMessage(text, "user");
    var typing = showTyping();

    postJson(root.dataset.sendUrl, { message: text })
      .then(function (res) {
        typing.remove();
        if (!res.ok) {
          var e = new Error(res.data.error || FRIENDLY_ERROR);
          e.friendly = true;
          throw e;
        }
        var links = [];
        if (res.data.ticket_url) links.push({ text: "Ver ticket #" + res.data.ticket_id, href: res.data.ticket_url });
        if (res.data.needs_account) {
          links.push({ text: "Ingresar", href: root.dataset.loginUrl });
          links.push({ text: "Crear cuenta", href: root.dataset.registerUrl });
        }
        addMessage(res.data.answer, "bot", links);
      })
      .catch(function (err) {
        typing.remove();
        addMessage(err && err.friendly ? err.message : FRIENDLY_ERROR, "bot");
      })
      .then(function () {
        busy = false;
        sendBtn.disabled = false;
        if (!authed && offeredQuick && !remaining.length && !nudged) {
          // Ya usó todas las preguntas rápidas: se le invita a registrarse para consultas más específicas
          nudged = true;
          addMessage("Esas eran las preguntas rápidas. Para consultas más específicas o para registrar una solicitud, ingresa o crea una cuenta.", "bot", [
            { text: "Ingresar", href: root.dataset.loginUrl },
            { text: "Crear cuenta", href: root.dataset.registerUrl }
          ]);
        } else {
          renderChips();
        }
        input.focus();
      });
  }

  launcher.addEventListener("click", function () { panel.hidden ? open() : close(); });
  closeBtn.addEventListener("click", close);
  if (humanBtn) humanBtn.addEventListener("click", askForHuman);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !panel.hidden) close();
  });
  // Con el chat abierto, Tab y Shift+Tab recorren solo sus controles (Esc lo cierra)
  panel.addEventListener("keydown", function (e) {
    if (e.key !== "Tab") return;
    var items = panel.querySelectorAll("a[href], button:not([disabled]), input:not([disabled])");
    if (!items.length) return;
    var first = items[0];
    var last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    sendMessage(input.value);
  });
})();
