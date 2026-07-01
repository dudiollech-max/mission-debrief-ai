/* Visionetics — Motion Background Canvas */
/* Draws tactical targeting reticles and geometric patterns */

(function () {
  const canvas = document.getElementById("motion-bg");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;

  // Set canvas size
  function resizeCanvas() {
    canvas.width = window.innerWidth * dpr;
    canvas.height = window.innerHeight * dpr;
    ctx.scale(dpr, dpr);
  }

  resizeCanvas();
  window.addEventListener("resize", resizeCanvas);

  // Colors
  const accentColor = "rgba(0, 217, 255, 0.15)";
  const accentGlow = "rgba(0, 217, 255, 0.08)";

  // Draw targeting reticle
  function drawReticle(x, y, radius, rotation = 0) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(rotation);

    // Outer circle
    ctx.strokeStyle = accentColor;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(0, 0, radius, 0, Math.PI * 2);
    ctx.stroke();

    // Inner circle
    ctx.beginPath();
    ctx.arc(0, 0, radius * 0.5, 0, Math.PI * 2);
    ctx.stroke();

    // Crosshair
    ctx.beginPath();
    ctx.moveTo(-radius * 1.2, 0);
    ctx.lineTo(-radius * 0.6, 0);
    ctx.moveTo(radius * 0.6, 0);
    ctx.lineTo(radius * 1.2, 0);
    ctx.moveTo(0, -radius * 1.2);
    ctx.lineTo(0, -radius * 0.6);
    ctx.moveTo(0, radius * 0.6);
    ctx.lineTo(0, radius * 1.2);
    ctx.stroke();

    // Quadrant markers
    const markerLen = radius * 0.3;
    const corners = [
      [-radius * 0.7, -radius * 0.7],
      [radius * 0.7, -radius * 0.7],
      [radius * 0.7, radius * 0.7],
      [-radius * 0.7, radius * 0.7],
    ];
    corners.forEach(([cx, cy]) => {
      ctx.beginPath();
      ctx.moveTo(cx - markerLen / 2, cy - markerLen / 2);
      ctx.lineTo(cx + markerLen / 2, cy - markerLen / 2);
      ctx.lineTo(cx + markerLen / 2, cy + markerLen / 2);
      ctx.lineTo(cx - markerLen / 2, cy + markerLen / 2);
      ctx.closePath();
      ctx.stroke();
    });

    ctx.restore();
  }

  // Draw grid pattern
  function drawGrid() {
    ctx.strokeStyle = accentGlow;
    ctx.lineWidth = 0.5;

    const gridSize = 120;
    for (let x = 0; x < window.innerWidth; x += gridSize) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, window.innerHeight);
      ctx.stroke();
    }

    for (let y = 0; y < window.innerHeight; y += gridSize) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(window.innerWidth, y);
      ctx.stroke();
    }
  }

  // Animation loop
  let time = 0;
  function animate() {
    ctx.fillStyle = "#05070b";
    ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);

    // Draw grid
    drawGrid();

    // Draw rotating reticles at key positions
    const reticles = [
      { x: window.innerWidth * 0.25, y: window.innerHeight * 0.35, r: 80 },
      { x: window.innerWidth * 0.75, y: window.innerHeight * 0.25, r: 60 },
      { x: window.innerWidth * 0.5, y: window.innerHeight * 0.7, r: 90 },
    ];

    reticles.forEach((r, i) => {
      drawReticle(r.x, r.y, r.r, time * (0.0005 + i * 0.0001));
    });

    time += 1;
    requestAnimationFrame(animate);
  }

  animate();
})();
