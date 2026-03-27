(() => {
  const zoomTarget = document.getElementById("zoomTarget");
  const modal = document.getElementById("zoomModal");
  const zoomImg = document.getElementById("zoomImg");
  if (!zoomTarget || !modal || !zoomImg) return;

  let scale = 1;
  const minScale = 1;
  const maxScale = 4;

  const setScale = (next) => {
    scale = Math.max(minScale, Math.min(maxScale, next));
    zoomImg.style.transform = `scale(${scale})`;
  };

  const open = () => {
    zoomImg.src = zoomTarget.src;
    setScale(1);
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  };

  const close = () => {
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    zoomImg.src = "";
  };

  zoomTarget.addEventListener("click", open);

  modal.addEventListener("click", (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement)) return;
    if (t.dataset.zoomClose === "true") close();
    if (t.dataset.zoomIn === "true") setScale(scale + 0.25);
    if (t.dataset.zoomOut === "true") setScale(scale - 0.25);
  });

  window.addEventListener("keydown", (e) => {
    if (modal.classList.contains("hidden")) return;
    if (e.key === "Escape") close();
  });

  // Mouse wheel zoom
  zoomImg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.15 : 0.15;
    setScale(scale + delta);
  }, { passive: false });

  // Basic pinch-to-zoom (touch)
  let lastDist = null;
  const getDist = (t1, t2) => {
    const dx = t1.clientX - t2.clientX;
    const dy = t1.clientY - t2.clientY;
    return Math.sqrt(dx * dx + dy * dy);
  };
  zoomImg.addEventListener("touchstart", (e) => {
    if (e.touches.length === 2) {
      lastDist = getDist(e.touches[0], e.touches[1]);
    }
  }, { passive: true });
  zoomImg.addEventListener("touchmove", (e) => {
    if (e.touches.length !== 2 || lastDist == null) return;
    const d = getDist(e.touches[0], e.touches[1]);
    const diff = (d - lastDist) / 200;
    setScale(scale + diff);
    lastDist = d;
  }, { passive: true });
  zoomImg.addEventListener("touchend", () => {
    lastDist = null;
  }, { passive: true });
})();

