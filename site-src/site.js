/* Progressive enhancement only. Every page is complete and usable without it. */
(function () {
  "use strict";
  document.querySelectorAll("[data-export-target]").forEach(function (button) {
    var area = document.getElementById(button.getAttribute("data-export-target"));
    if (!area) { return; }
    button.hidden = false;
    button.addEventListener("click", function () {
      var blob = new Blob([area.value], { type: "application/json" });
      var link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = button.getAttribute("data-filename") || "annotation.json";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(link.href);
    });
  });
})();
