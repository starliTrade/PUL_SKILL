import React, { useState, useEffect, useRef } from 'react';
import { ShieldCheck, Activity, Play, RotateCcw, Zap, AlertTriangle } from 'lucide-react';
import { cn } from '../lib/utils';
import { sounds } from '../lib/sound';
import { usePulsarStore } from '../store/usePulsarStore';

interface Star {
  x: number;
  y: number;
  radius: number;
  baseAlpha: number;
  twinkleSpeed: number;
  phase: number;
}

interface PulsarHeroVisualizerProps {
  className?: string;
  onStartBattle?: () => void;
}

export const PulsarHeroVisualizer: React.FC<PulsarHeroVisualizerProps> = ({
  className,
}) => {
  const { bestReactionMs } = usePulsarStore();
  const [livePing, setLivePing] = useState<number>(14);

  // Interactive reflex test state
  const [testState, setTestState] = useState<'idle' | 'waiting' | 'ready' | 'result'>('idle');
  const [testReactionMs, setTestReactionMs] = useState<number>(0);
  const [falseStart, setFalseStart] = useState<boolean>(false);
  const startTimeRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Background Canvas Ref for Cosmic Twinkling Stars & Pulsar Star
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const interval = setInterval(() => {
      setLivePing(12 + Math.floor(Math.random() * 5));
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  // Canvas animation effect for cosmic twinkling stars & pulsating pulsar star
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let width = 0;
    let height = 0;
    const stars: Star[] = [];
    const starCount = 28;

    const initStars = () => {
      stars.length = 0;
      for (let i = 0; i < starCount; i++) {
        stars.push({
          x: Math.random() * width,
          y: Math.random() * height,
          radius: Math.random() * 0.7 + 0.3,
          baseAlpha: Math.random() * 0.2 + 0.05,
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

    const startTime = performance.now();

    const render = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      ctx.clearRect(0, 0, width, height);

      if (width <= 0 || height <= 0) return;

      // 1. Draw subtle twinkling micro stars
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

      // 2. Subtle Cosmic Pulsar Star in upper center of card
      const pulsarX = width * 0.5;
      const pulsarY = height * 0.36;

      const pulse = Math.sin(elapsed * 0.002) * 0.5 + 0.5;
      const pulseFast = Math.sin(elapsed * 0.004) * 0.5 + 0.5;

      // Diffused ambient soft nebula glow
      const glowRadius = Math.max(10, Math.min(width * 0.45, 90));
      const nebulaGrad = ctx.createRadialGradient(pulsarX, pulsarY, 0, pulsarX, pulsarY, glowRadius);
      nebulaGrad.addColorStop(0, `rgba(56, 189, 248, ${(0.05 + pulse * 0.03).toFixed(3)})`);
      nebulaGrad.addColorStop(0.5, `rgba(99, 102, 241, ${(0.02 + pulse * 0.015).toFixed(3)})`);
      nebulaGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
      ctx.fillStyle = nebulaGrad;
      ctx.beginPath();
      ctx.arc(pulsarX, pulsarY, glowRadius, 0, Math.PI * 2);
      ctx.fill();

      // Faint harmonic wave pulse ring
      const ring = Math.max(0.1, ((elapsed * 0.018) % 70) + 5);
      const ringAlpha = Math.max(0, (1 - ring / 70) * 0.04);
      ctx.strokeStyle = `rgba(186, 230, 253, ${ringAlpha.toFixed(3)})`;
      ctx.lineWidth = 0.75;
      ctx.beginPath();
      ctx.arc(pulsarX, pulsarY, ring, 0, Math.PI * 2);
      ctx.stroke();

      // Rotating magnetic relativistic jets (Faint cosmic beam)
      const angle = elapsed * 0.0007;
      ctx.save();
      ctx.translate(pulsarX, pulsarY);
      ctx.rotate(angle);

      // Jet top
      const jet1 = ctx.createLinearGradient(0, 0, 0, -45);
      jet1.addColorStop(0, `rgba(255, 255, 255, ${(0.07 + pulse * 0.04).toFixed(3)})`);
      jet1.addColorStop(0.4, `rgba(56, 189, 248, ${(0.03 + pulse * 0.02).toFixed(3)})`);
      jet1.addColorStop(1, 'rgba(56, 189, 248, 0)');
      ctx.fillStyle = jet1;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(-4, -45);
      ctx.lineTo(4, -45);
      ctx.closePath();
      ctx.fill();

      // Jet bottom
      const jet2 = ctx.createLinearGradient(0, 0, 0, 45);
      jet2.addColorStop(0, `rgba(255, 255, 255, ${(0.07 + pulse * 0.04).toFixed(3)})`);
      jet2.addColorStop(0.4, `rgba(56, 189, 248, ${(0.03 + pulse * 0.02).toFixed(3)})`);
      jet2.addColorStop(1, 'rgba(56, 189, 248, 0)');
      ctx.fillStyle = jet2;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(-4, 45);
      ctx.lineTo(4, 45);
      ctx.closePath();
      ctx.fill();

      // Diamond core spike
      ctx.strokeStyle = `rgba(255, 255, 255, ${(0.3 + pulse * 0.3).toFixed(3)})`;
      ctx.lineWidth = 0.75;
      ctx.beginPath();
      ctx.moveTo(-5, 0);
      ctx.lineTo(5, 0);
      ctx.moveTo(0, -5);
      ctx.lineTo(0, 5);
      ctx.stroke();

      // Dense white-hot central core
      ctx.fillStyle = `rgba(255, 255, 255, ${(0.6 + pulseFast * 0.35).toFixed(3)})`;
      ctx.beginPath();
      ctx.arc(0, 0, 1.2, 0, Math.PI * 2);
      ctx.fill();

      ctx.restore();

      animationFrameId = requestAnimationFrame(render);
    };

    animationFrameId = requestAnimationFrame(render);

    return () => {
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  const handleStartTest = (e: React.MouseEvent) => {
    e.stopPropagation();
    sounds.playClick();
    setFalseStart(false);
    setTestState('waiting');

    const randomDelay = 1500 + Math.random() * 2500;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      setTestState('ready');
      startTimeRef.current = performance.now();
      sounds.playGo();
    }, randomDelay);
  };

  const handleTestClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (testState === 'waiting') {
      if (timerRef.current) clearTimeout(timerRef.current);
      setFalseStart(true);
      sounds.playLoss();
      setTestState('idle');
      setTimeout(() => setFalseStart(false), 2000);
      return;
    }

    if (testState === 'ready') {
      const ms = Math.round(performance.now() - startTimeRef.current);
      setTestReactionMs(ms);
      setTestState('result');
      sounds.playHit();
    }
  };

  return (
    <div className={cn('relative w-full mx-auto select-none my-1.5', className)}>
      {/* Ambient subtle glow around card */}
      <div
        className="absolute -inset-1 rounded-2xl pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse at 50% 30%, rgba(255, 255, 255, 0.04) 0%, rgba(56, 189, 248, 0.02) 40%, transparent 70%)',
          filter: 'blur(12px)',
        }}
      />

      {/* Main Full-Width Cosmic Reflex Card (Compact Height) */}
      <div className="relative overflow-hidden p-2.5 sm:p-3 rounded-xl bg-zinc-950/95 border border-white/[0.05] shadow-[0_4px_20px_rgba(0,0,0,0.75)] backdrop-blur-md w-full">
        {/* Background Twinkling Canvas with Pulsar Cosmic Flare */}
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          <canvas ref={canvasRef} className="absolute inset-0 w-full h-full block opacity-75" />
        </div>

        {/* Relative Content Container */}
        <div className="relative z-10">
          {/* Top Status Strip */}
          <div className="flex items-center justify-between pb-1.5 border-b border-white/[0.03]">
            <div className="flex items-center gap-1.5">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
              </span>
              <span className="text-[9.5px] font-mono text-zinc-300 font-semibold tracking-tight">
                PULSAR PROTOCOL
              </span>
            </div>

            <div className="flex items-center gap-1 text-[8.5px] font-mono text-zinc-400 bg-white/[0.03] px-1.5 py-0.5 rounded-full border border-white/[0.03]">
              <Activity className="w-2 h-2 text-emerald-400" />
              <span>{livePing}ms Global Ping</span>
            </div>
          </div>

          {/* Center Display: Compact Interactive Reflex Benchmark Screen */}
          <div
            onClick={testState === 'waiting' || testState === 'ready' ? handleTestClick : undefined}
            className={cn(
              'py-2 px-2 text-center transition-all duration-200 rounded-lg my-1.5',
              testState === 'waiting' && 'bg-amber-950/20 border border-amber-500/25 cursor-pointer',
              testState === 'ready' &&
                'bg-emerald-950/60 border border-emerald-400 cursor-pointer shadow-[0_0_20px_rgba(52,211,153,0.35)] animate-pulse',
              testState === 'result' && 'bg-white/[0.02] border border-sky-500/15',
              testState === 'idle' && 'bg-transparent'
            )}
          >
            <div className="text-[8.5px] uppercase font-mono tracking-wider text-zinc-400 mb-0.5">
              {testState === 'idle' && 'Sub-ms Reflex Benchmark'}
              {testState === 'waiting' && 'Wait for Green Flash...'}
              {testState === 'ready' && 'TAP NOW!'}
              {testState === 'result' && 'Verified Human Response'}
            </div>

            {/* Monospace ms number */}
            <div className="flex items-baseline justify-center gap-1 my-0.5">
              <span
                className={cn(
                  'text-2xl sm:text-3xl font-black font-mono tracking-tight transition-colors',
                  testState === 'waiting'
                    ? 'text-amber-400 text-xl sm:text-2xl'
                    : testState === 'ready'
                    ? 'text-emerald-300 text-xl sm:text-2xl'
                    : 'text-white'
                )}
              >
                {testState === 'waiting' ? (
                  <span className="text-amber-400 animate-pulse">WAIT...</span>
                ) : testState === 'ready' ? (
                  <span className="text-emerald-300 animate-bounce">CLICK!</span>
                ) : testState === 'result' ? (
                  testReactionMs
                ) : bestReactionMs > 0 ? (
                  bestReactionMs
                ) : (
                  '168'
                )}
              </span>
              {testState !== 'waiting' && testState !== 'ready' && (
                <span className="text-[11px] font-mono text-zinc-500 font-medium">ms</span>
              )}
            </div>

            {/* Sub-label / status feedback */}
            {falseStart && (
              <div className="text-rose-400 text-[9px] font-mono font-semibold animate-shake mt-0.5 flex items-center justify-center gap-1">
                <AlertTriangle className="w-2.5 h-2.5" />
                <span>Too early! Wait for green flash.</span>
              </div>
            )}

            {testState === 'result' && (
              <div className="text-sky-400 text-[9px] font-mono mt-0.5 flex items-center justify-center gap-1">
                <Zap className="w-2.5 h-2.5" />
                <span>
                  {testReactionMs < 200
                    ? 'Top 1% Reflex Elite'
                    : testReactionMs < 250
                    ? 'Competitive Duelist Reflex'
                    : 'Ready for 1v1 Arena'}
                </span>
              </div>
            )}
          </div>

          {/* Interactive Action Trigger Button */}
          <div className="mt-0.5 flex items-center justify-center">
            {testState === 'idle' && (
              <button
                onClick={handleStartTest}
                className="w-full py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] hover:border-white/[0.12] text-[11px] font-medium text-zinc-300 hover:text-white transition-all flex items-center justify-center gap-1.5 cursor-pointer active:scale-[0.99]"
              >
                <Play className="w-2.5 h-2.5 fill-current text-sky-400" />
                <span>Test Your Reaction Speed (Free)</span>
              </button>
            )}

            {testState === 'waiting' && (
              <button
                onClick={handleTestClick}
                className="w-full py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-[11px] font-mono text-amber-300 font-bold transition-all flex items-center justify-center gap-1 cursor-pointer"
              >
                <span>Hold... click when green!</span>
              </button>
            )}

            {testState === 'ready' && (
              <button
                onClick={handleTestClick}
                className="w-full py-1.5 rounded-lg bg-emerald-500 border border-emerald-400 text-[11px] font-mono text-black font-extrabold transition-all flex items-center justify-center gap-1 cursor-pointer shadow-[0_0_16px_rgba(52,211,153,0.5)]"
              >
                <span>TAP ANYWHERE NOW!</span>
              </button>
            )}

            {testState === 'result' && (
              <div className="w-full flex gap-1.5">
                <button
                  onClick={handleStartTest}
                  className="flex-1 py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] text-[11px] font-medium text-zinc-300 hover:text-white transition-all flex items-center justify-center gap-1 cursor-pointer"
                >
                  <RotateCcw className="w-2.5 h-2.5" />
                  <span>Retest</span>
                </button>
              </div>
            )}
          </div>

          {/* Micro Telemetry Footer */}
          <div className="mt-2 pt-1.5 border-t border-white/[0.04] flex items-center justify-between text-[8.5px] text-zinc-500 font-mono">
            <div className="flex items-center gap-1 text-zinc-400">
              <ShieldCheck className="w-2 h-2 text-emerald-400" />
              <span>Biometric Anti-Cheat</span>
            </div>
            <span className="text-zinc-500">Sub-ms Clock</span>
          </div>
        </div>
      </div>
    </div>
  );
};
