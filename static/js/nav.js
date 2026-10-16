/* Menú desplegable para celulares: el botón abre y cierra la navegación. Sin JavaScript el menú queda visible. */
(function () {
  var toggle = document.querySelector(".nav-toggle");
  var header = document.querySelector(".site-header");
  if (!toggle || !header) return;

  function setOpen(open) {
    header.classList.toggle("nav-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.setAttribute("aria-label", open ? "Cerrar menú" : "Abrir menú");
  }

  toggle.addEventListener("click", function () {
    setOpen(!header.classList.contains("nav-open"));
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && header.classList.contains("nav-open")) {
      setOpen(false);
      toggle.focus();
    }
  });
})();
