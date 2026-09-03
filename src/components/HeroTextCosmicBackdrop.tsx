import React, { useEffect, useRef } from 'react';

interface Star {
  x: number;
  y: number;
  radius: number;
  baseAlpha: number;
  alpha: number;
  twinkleSpeed: number;
  phase: number;
  isPulsarCore?: boolean;
}

export const HeroTextCosmicBackdrop: React.FC<{ className?: string }> = ({ className = '' }) => {
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
    const starCount = 38;

    const initStars = () => {
      stars.length = 0;
      for (let i = 0; i < starCount; i++) {
        // Distribute stars mostly around the middle/sides so text is framed beautifully
        stars.push({
          x: Math.random() * width,
          y: Math.random() * height,
          radius: Math.random() * 0.85 + 0.45, // 0.45px to 1.3px
          baseAlpha: Math.random() * 0.22 + 0.05, // 0.05 - 0.27 (subtle & soft)
          alpha: 0.1,
          twinkleSpeed: Math.random() * 0.002 + 0.001,
          phase: Math.random() * Math.PI * 2,
        });
      }
    };

    const handleResize = () => {
      if (!canvas || !canvas.parentElement) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas.parentElement.clientWidth;
      height = canvas.parentElement.clientHeight;

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

      // 1. Central Ambient Pulsar Fog / Subtle Glow behind the headline
      const centerX = width * 0.5;
      const centerY = height * 0.45;

      const pulse = Math.sin(elapsed * 0.0016) * 0.5 + 0.5;
      const pulseFast = Math.sin(elapsed * 0.003) * 0.5 + 0.5;

      // Soft diffused glow right behind "Challenge your skill"
      const glowRadius = Math.max(10, Math.min(width * 0.55, 180));
      const glowGrad = ctx.createRadialGradient(
        centerX,
        centerY,
        0,
        centerX,
        centerY,
        glowRadius
      );
      glowGrad.addColorStop(0, `rgba(56, 189, 248, ${(0.045 + pulse * 0.025).toFixed(3)})`);
      glowGrad.addColorStop(0.4, `rgba(99, 102, 241, ${(0.025 + pulse * 0.015).toFixed(3)})`);
      glowGrad.addColorStop(0.8, 'rgba(15, 23, 42, 0.01)');
      glowGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');

      ctx.fillStyle = glowGrad;
      ctx.beginPath();
      ctx.arc(centerX, centerY, glowRadius, 0, Math.PI * 2);
      ctx.fill();

      // 2. Faint Radio Pulsar Rings expanding softly from behind the title
      const ring1 = Math.max(0.1, ((elapsed * 0.015) % 140) + 10);
      const alpha1 = Math.max(0, (1 - ring1 / 140) * 0.035);
      ctx.strokeStyle = `rgba(186, 230, 253, ${alpha1.toFixed(3)})`;
      ctx.lineWidth = 0.65;
      ctx.beginPath();
      ctx.arc(centerX, centerY, ring1, 0, Math.PI * 2);
      ctx.stroke();

      const ring2 = Math.max(0.1, (((elapsed * 0.015) + 70) % 140) + 10);
      const alpha2 = Math.max(0, (1 - ring2 / 140) * 0.03);
      ctx.strokeStyle = `rgba(165, 180, 252, ${alpha2.toFixed(3)})`;
      ctx.lineWidth = 0.65;
      ctx.beginPath();
      ctx.arc(centerX, centerY, ring2, 0, Math.PI * 2);
      ctx.stroke();

      // 3. Faint Pulsar Star Spark positioned right near the upper-right corner of the headline
      const pulsarStarX = width * 0.78;
      const pulsarStarY = height * 0.28;

      // Soft flare behind the mini pulsar
      const miniPulsarGlow = ctx.createRadialGradient(
        pulsarStarX,
        pulsarStarY,
        0,
        pulsarStarX,
        pulsarStarY,
        35
      );
      miniPulsarGlow.addColorStop(0, `rgba(56, 189, 248, ${(0.08 + pulseFast * 0.05).toFixed(3)})`);
      miniPulsarGlow.addColorStop(1, 'rgba(56, 189, 248, 0)');
      ctx.fillStyle = miniPulsarGlow;
      ctx.beginPath();
      ctx.arc(pulsarStarX, pulsarStarY, 35, 0, Math.PI * 2);
      ctx.fill();

      // Mini 4-point diamond cross flare
      ctx.strokeStyle = `rgba(255, 255, 255, ${(0.22 + pulse * 0.25).toFixed(3)})`;
      ctx.lineWidth = 0.75;
      ctx.beginPath();
      ctx.moveTo(pulsarStarX - 8, pulsarStarY);
      ctx.lineTo(pulsarStarX + 8, pulsarStarY);
      ctx.moveTo(pulsarStarX, pulsarStarY - 8);
      ctx.lineTo(pulsarStarX, pulsarStarY + 8);
      ctx.stroke();

      // Mini pulsar center dot
      ctx.fillStyle = `rgba(255, 255, 255, ${(0.45 + pulse * 0.4).toFixed(3)})`;
      ctx.beginPath();
      ctx.arc(pulsarStarX, pulsarStarY, 1.2, 0, Math.PI * 2);
      ctx.fill();

      // 4. Draw Twinkling Micro Stars
      for (let i = 0; i < stars.length; i++) {
        const star = stars[i];
        if (star.radius <= 0) continue;
        const wave = Math.sin(elapsed * star.twinkleSpeed + star.phase);
        const currentAlpha = Math.max(0.02, star.baseAlpha + wave * (star.baseAlpha * 0.8));

        ctx.fillStyle = `rgba(255, 255, 255, ${currentAlpha.toFixed(3)})`;
        ctx.beginPath();
        ctx.arc(star.x, star.y, Math.max(0.1, star.radius), 0, Math.PI * 2);
        ctx.fill();
      }

      animationFrameId = requestAnimationFrame(render);
    };

    animationFrameId = requestAnimationFrame(render);

    return () => {
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <div className={`absolute inset-0 pointer-events-none overflow-hidden rounded-3xl ${className}`}>
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full block" />
    </div>
  );
};
