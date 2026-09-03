import React, { useEffect, useRef } from 'react';

interface Star {
  x: number;
  y: number;
  radius: number;
  baseAlpha: number;
  alpha: number;
  twinkleSpeed: number;
  phase: number;
}

export const PulsarCosmicBackground: React.FC<{ className?: string }> = ({ className = '' }) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let width = 0;
    let height = 0;

    const stars: Star[] = [];
    const starCount = 65;

    const initStars = () => {
      stars.length = 0;
      for (let i = 0; i < starCount; i++) {
        stars.push({
          x: Math.random() * width,
          y: Math.random() * height,
          radius: Math.random() * 0.9 + 0.5, // 0.5px to 1.4px
          baseAlpha: Math.random() * 0.18 + 0.04, // Ultra-faint 0.04 - 0.22
          alpha: 0.1,
          twinkleSpeed: Math.random() * 0.0015 + 0.0008,
          phase: Math.random() * Math.PI * 2,
        });
      }
    };

    const handleResize = () => {
      if (!canvas) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas.parentElement?.clientWidth || window.innerWidth;
      height = canvas.parentElement?.clientHeight || window.innerHeight;

      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      ctx.scale(dpr, dpr);
      initStars();
    };

    handleResize();
    window.addEventListener('resize', handleResize);

    let startTime = performance.now();

    const render = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      ctx.clearRect(0, 0, width, height);

      // Safety: ensure positive dimensions before drawing
      if (width <= 0 || height <= 0) return;

      // 1. Draw Tiny Twinkling Stars
      for (let i = 0; i < stars.length; i++) {
        const star = stars[i];
        if (star.radius <= 0) continue;
        // Smooth sine wave twinkle
        const wave = Math.sin(elapsed * star.twinkleSpeed + star.phase);
        const currentAlpha = Math.max(0.02, star.baseAlpha + wave * (star.baseAlpha * 0.7));

        ctx.fillStyle = `rgba(255, 255, 255, ${currentAlpha.toFixed(3)})`;
        ctx.beginPath();
        ctx.arc(star.x, star.y, Math.max(0.1, star.radius), 0, Math.PI * 2);
        ctx.fill();
      }

      // 2. Draw Subtle Distant Pulsar Star (Placed in the upper hero area: 50% X, 20% Y)
      const pulsarX = width * 0.5;
      const pulsarY = Math.min(height * 0.22, 170);

      // Pulsar rhythmic breathing
      const pulse = Math.sin(elapsed * 0.0018) * 0.5 + 0.5; // 0 to 1
      const pulseSlow = Math.sin(elapsed * 0.0009) * 0.5 + 0.5;

      // Ultra-faint radial glow nebula
      const nebulaRadius = Math.max(10, Math.min(220, width * 0.6));
      const nebulaGrad = ctx.createRadialGradient(pulsarX, pulsarY, 2, pulsarX, pulsarY, nebulaRadius);
      nebulaGrad.addColorStop(0, `rgba(56, 189, 248, ${(0.035 + pulse * 0.025).toFixed(3)})`);
      nebulaGrad.addColorStop(0.35, `rgba(99, 102, 241, ${(0.018 + pulse * 0.012).toFixed(3)})`);
      nebulaGrad.addColorStop(0.75, 'rgba(15, 23, 42, 0.01)');
      nebulaGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');

      ctx.fillStyle = nebulaGrad;
      ctx.beginPath();
      ctx.arc(pulsarX, pulsarY, nebulaRadius, 0, Math.PI * 2);
      ctx.fill();

      // Outer faint harmonic wave rings (emanating outward like radio waves)
      const ringRadius1 = Math.max(0.1, ((elapsed * 0.02) % 160) + 10);
      const ringAlpha1 = Math.max(0, (1 - ringRadius1 / 160) * 0.04);
      ctx.strokeStyle = `rgba(186, 230, 253, ${ringAlpha1.toFixed(3)})`;
      ctx.lineWidth = 0.75;
      ctx.beginPath();
      ctx.arc(pulsarX, pulsarY, ringRadius1, 0, Math.PI * 2);
      ctx.stroke();

      const ringRadius2 = Math.max(0.1, (((elapsed * 0.02) + 80) % 160) + 10);
      const ringAlpha2 = Math.max(0, (1 - ringRadius2 / 160) * 0.035);
      ctx.strokeStyle = `rgba(165, 180, 252, ${ringAlpha2.toFixed(3)})`;
      ctx.lineWidth = 0.75;
      ctx.beginPath();
      ctx.arc(pulsarX, pulsarY, ringRadius2, 0, Math.PI * 2);
      ctx.stroke();

      // Dual rotating magnetic relativistic jets (Faint cone beams)
      const angle = elapsed * 0.0006;
      ctx.save();
      ctx.translate(pulsarX, pulsarY);
      ctx.rotate(angle);

      // Jet 1 (Top)
      const jetGrad1 = ctx.createLinearGradient(0, 0, 0, -140);
      jetGrad1.addColorStop(0, `rgba(255, 255, 255, ${(0.06 + pulse * 0.03).toFixed(3)})`);
      jetGrad1.addColorStop(0.3, `rgba(56, 189, 248, ${(0.03 + pulse * 0.02).toFixed(3)})`);
      jetGrad1.addColorStop(1, 'rgba(56, 189, 248, 0)');

      ctx.fillStyle = jetGrad1;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(-12, -140);
      ctx.lineTo(12, -140);
      ctx.closePath();
      ctx.fill();

      // Jet 2 (Bottom)
      const jetGrad2 = ctx.createLinearGradient(0, 0, 0, 140);
      jetGrad2.addColorStop(0, `rgba(255, 255, 255, ${(0.06 + pulse * 0.03).toFixed(3)})`);
      jetGrad2.addColorStop(0.3, `rgba(56, 189, 248, ${(0.03 + pulse * 0.02).toFixed(3)})`);
      jetGrad2.addColorStop(1, 'rgba(56, 189, 248, 0)');

      ctx.fillStyle = jetGrad2;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(-12, 140);
      ctx.lineTo(12, 140);
      ctx.closePath();
      ctx.fill();

      // Pulsar Compact Dense Core
      const coreAlpha = 0.4 + pulse * 0.35;
      ctx.fillStyle = `rgba(255, 255, 255, ${coreAlpha.toFixed(3)})`;
      ctx.beginPath();
      ctx.arc(0, 0, 1.6 + pulseSlow * 0.4, 0, Math.PI * 2);
      ctx.fill();

      // Core Diamond Spike Flair (Micro 4-point star)
      ctx.strokeStyle = `rgba(255, 255, 255, ${(0.25 + pulse * 0.2).toFixed(3)})`;
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(-10, 0);
      ctx.lineTo(10, 0);
      ctx.moveTo(0, -10);
      ctx.lineTo(0, 10);
      ctx.stroke();

      ctx.restore();

      animationFrameId = requestAnimationFrame(render);
    };

    animationFrameId = requestAnimationFrame(render);

    return () => {
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <div className={`absolute inset-0 pointer-events-none overflow-hidden ${className}`}>
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full block" />
    </div>
  );
};
