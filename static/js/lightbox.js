/* Foto ampliada: al tocar una foto de "Trabajos por segmento" se abre en una ventana con flechas, contador y
   texto. Sin JavaScript (o en un navegador sin <dialog>) cada foto sigue abriéndose en una pestaña nueva. */
(function () {
  var dialog = document.getElementById("lightbox");
  if (!dialog || typeof dialog.showModal !== "function") return;

  var image = dialog.querySelector("img");
  var caption = dialog.querySelector(".lb-caption");
  var count = dialog.querySelector(".lb-count");
  var links = [];
  var index = 0;

  function show(i) {
    index = (i + links.length) % links.length;
    var link = links[index];
    image.src = link.href;
    image.alt = link.getAttribute("data-caption") || "";
    caption.textContent = link.getAttribute("data-caption") || "";
    count.textContent = links.length > 1 ? "Foto " + (index + 1) + " de " + links.length : "";
    dialog.classList.toggle("lb-single", links.length < 2);
    // Precarga las vecinas para que las flechas respondan al instante.
    [index - 1, index + 1].forEach(function (n) {
      if (links.length > 1) new Image().src = links[(n + links.length) % links.length].href;
    });
  }

  document.querySelectorAll("a[data-lightbox]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      if (event.ctrlKey || event.metaKey || event.shiftKey) return; // deja abrir en pestaña nueva
      event.preventDefault();
      var group = link.getAttribute("data-group");
      links = Array.prototype.filter.call(document.querySelectorAll("a[data-lightbox]"), function (other) {
        return other.getAttribute("data-group") === group;
      });
      dialog.showModal();
      show(links.indexOf(link));
    });
  });

  dialog.querySelector(".lb-prev").addEventListener("click", function () { show(index - 1); });
  dialog.querySelector(".lb-next").addEventListener("click", function () { show(index + 1); });
  dialog.querySelector(".lb-close").addEventListener("click", function () { dialog.close(); });
  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) dialog.close(); // clic en el fondo oscuro
  });
  dialog.addEventListener("keydown", function (event) {
    if (links.length < 2) return;
    if (event.key === "ArrowLeft") { event.preventDefault(); show(index - 1); }
    if (event.key === "ArrowRight") { event.preventDefault(); show(index + 1); }
  });
  dialog.addEventListener("close", function () { image.removeAttribute("src"); });
})();
