"use strict";
document.querySelectorAll("[data-gallery]").forEach(gallery => {
  const slides = [...gallery.querySelectorAll(".gallery-slide")];
  if (!slides.length) {
    gallery.querySelectorAll(".gallery-arrow").forEach(button => button.hidden = true);
    return;
  }
  let index = 0, startX = null, startY = null;
  const show = next => {
    index = (next + slides.length) % slides.length;
    slides.forEach((slide, i) => slide.classList.toggle("is-active", i === index));
    const count = gallery.querySelector("[data-gallery-count]");
    if (count) count.textContent = `${index + 1} / ${slides.length}`;
  };
  gallery.dataset.ready = "true";
  gallery.querySelector("[data-prev]")?.addEventListener("click", () => show(index - 1));
  gallery.querySelector("[data-next]")?.addEventListener("click", () => show(index + 1));
  gallery.querySelectorAll(".gallery-arrow").forEach(button => button.hidden = slides.length < 2);
  gallery.addEventListener("touchstart", event => {
    startX = event.changedTouches[0].clientX;
    startY = event.changedTouches[0].clientY;
  }, {passive:true});
  gallery.addEventListener("touchend", event => {
    if (startX === null) return;
    const dx = event.changedTouches[0].clientX - startX;
    const dy = event.changedTouches[0].clientY - startY;
    if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy)) show(index + (dx < 0 ? 1 : -1));
    startX = null;
    startY = null;
  }, {passive:true});
  show(0);
});
