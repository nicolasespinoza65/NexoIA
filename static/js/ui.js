/* Pequeñas mejoras de uso en todo el sitio. Todo es opcional: sin JavaScript la página funciona igual. */
(function () {
  // 1) Avisos (mensajes de éxito o error): botón para cerrarlos.
  document.querySelectorAll(".flash").forEach(function (flash) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "flash-close";
    button.setAttribute("aria-label", "Cerrar aviso");
    button.textContent = "\u00d7";
    button.addEventListener("click", function () { flash.remove(); });
    flash.classList.add("has-close");
    flash.appendChild(button);
  });

  // 2) Menú "Administrar": se cierra al tocar fuera o con Escape.
  var groups = document.querySelectorAll(".nav-group");
  document.addEventListener("click", function (event) {
    groups.forEach(function (group) {
      if (group.open && !group.contains(event.target)) group.open = false;
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    groups.forEach(function (group) {
      if (group.open) { group.open = false; group.querySelector("summary").focus(); }
    });
  });

  // 3) Campos de fotos: miniaturas de lo elegido (y aviso si alguna pesa demasiado).
  var MAX_MB = 5;
  document.querySelectorAll("input[type=file]").forEach(function (input) {
    var list = document.createElement("ul");
    list.className = "file-previews";
    list.setAttribute("aria-live", "polite");
    input.insertAdjacentElement("afterend", list);
    var urls = [];

    function clear() {
      urls.forEach(function (url) { URL.revokeObjectURL(url); });
      urls = [];
      list.textContent = "";
    }

    input.addEventListener("change", function () {
      clear();
      Array.prototype.forEach.call(input.files, function (file) {
        if (file.type.indexOf("image/") !== 0) return;
        var item = document.createElement("li");
        var img = document.createElement("img");
        var url = URL.createObjectURL(file);
        urls.push(url);
        img.src = url;
        img.alt = "";
        var name = document.createElement("span");
        var mb = file.size / 1048576;
        name.textContent = file.name + " (" + mb.toFixed(1).replace(".", ",") + " MB)";
        if (mb > MAX_MB) {
          name.className = "too-big";
          name.textContent += " \u2013 supera los " + MAX_MB + " MB";
        }
        item.appendChild(img);
        item.appendChild(name);
        list.appendChild(item);
      });
    });

    // Resalta la zona mientras se arrastran archivos encima.
    ["dragenter", "dragover"].forEach(function (name) {
      input.addEventListener(name, function () { input.classList.add("is-over"); });
    });
    ["dragleave", "drop"].forEach(function (name) {
      input.addEventListener(name, function () { input.classList.remove("is-over"); });
    });
  });
})();
