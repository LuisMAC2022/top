/* The page remains complete without JavaScript; this adds optional spoken guidance. */
(function () {
  "use strict";

  var synthesis = window.speechSynthesis;
  var status = document.getElementById("speech-status");
  var listenButtons = Array.from(document.querySelectorAll("[data-speech]"));
  var readAll = document.getElementById("read-all");
  var stop = document.getElementById("stop-speech");

  function setStatus(message) {
    status.textContent = message;
  }

  if (!synthesis || typeof window.SpeechSynthesisUtterance === "undefined") {
    setStatus("La síntesis de voz no está disponible en este navegador. Usa las indicaciones escritas.");
    readAll.disabled = true;
    stop.disabled = true;
    listenButtons.forEach(function (button) { button.disabled = true; });
    return;
  }

  function speak(text, label) {
    synthesis.cancel();
    var utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "es-ES";
    utterance.rate = 0.95;
    utterance.onstart = function () { setStatus("Reproduciendo: " + label + "."); };
    utterance.onend = function () { setStatus("Lectura finalizada."); };
    utterance.onerror = function () { setStatus("No se pudo reproducir el audio. La indicación sigue disponible como texto."); };
    synthesis.speak(utterance);
  }

  listenButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      speak(button.dataset.speech, button.closest("article").querySelector("h3").textContent);
    });
  });

  readAll.addEventListener("click", function () {
    var completeGuide = listenButtons.map(function (button) { return button.dataset.speech; }).join(" ");
    speak(completeGuide, "todas las verificaciones");
  });

  stop.addEventListener("click", function () {
    synthesis.cancel();
    setStatus("Audio detenido.");
  });
})();
