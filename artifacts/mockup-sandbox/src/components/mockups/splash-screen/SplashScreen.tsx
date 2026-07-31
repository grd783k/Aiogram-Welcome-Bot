import { useEffect, useRef, useState } from "react";

// ─── Config ───────────────────────────────────────────────────────────────────
const LOGO_DELAY_MS    = 280;   // ms before progress bar starts
const PROGRESS_DURATION = 1600; // ms for 0 → 100%
const HOLD_MS          = 550;   // ms to hold at 100% before fade-out
const FADE_MS          = 380;   // ms for the fade-out

const MESSAGES = [
  "Initialisation…",
  "Connexion sécurisée…",
  "Chargement du shop…",
  "Vérification des données…",
  "Finalisation…",
];

// Simulated first name (in production: Telegram.WebApp.initDataUnsafe.user.first_name)
const FIRST_NAME = "Jean";

// ─── Component ────────────────────────────────────────────────────────────────
export function SplashScreen() {
  const [progress, setProgress]   = useState(0);
  const [msgIndex, setMsgIndex]   = useState(0);
  const [welcome,  setWelcome]    = useState(false);
  const [fadeOut,  setFadeOut]    = useState(false);
  const [done,     setDone]       = useState(false);

  const startRef = useRef<number | null>(null);
  const rafRef   = useRef<number | null>(null);

  useEffect(() => {
    // Phase 1: Logo CSS animation plays for LOGO_DELAY_MS
    const logoTimer = setTimeout(() => {
      // Phase 2: Animate progress via RAF (smooth 60 fps)
      const tick = (now: number) => {
        if (startRef.current === null) startRef.current = now;
        const elapsed = now - startRef.current;
        const pct = Math.min(100, Math.floor((elapsed / PROGRESS_DURATION) * 100));

        setProgress(pct);
        setMsgIndex(Math.min(Math.floor(pct / 20), MESSAGES.length - 1));

        if (pct < 100) {
          rafRef.current = requestAnimationFrame(tick);
        } else {
          // Phase 3: Show welcome, then fade out
          setWelcome(true);
          setTimeout(() => {
            setFadeOut(true);
            setTimeout(() => setDone(true), FADE_MS);
          }, HOLD_MS);
        }
      };
      rafRef.current = requestAnimationFrame(tick);
    }, LOGO_DELAY_MS);

    return () => {
      clearTimeout(logoTimer);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  // ── After splash: placeholder for the real app content ──────────────────────
  if (done) {
    return (
      <div style={{
        height: "100vh", background: "#0a0a0a",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "system-ui", color: "rgba(255,255,255,0.3)", fontSize: 13,
      }}>
        [ Contenu de la Mini App ]
      </div>
    );
  }

  return (
    <>
      {/* ── Keyframes injected once ─────────────────────────────────────────── */}
      <style>{`
        @keyframes logo-in {
          0%   { opacity: 0; transform: scale(0.80); }
          60%  { opacity: 1; transform: scale(1.07); }
          100% { opacity: 1; transform: scale(1.00); }
        }
        @keyframes glow-pulse {
          0%, 100% { opacity: 0.65; transform: scale(1.00); }
          50%       { opacity: 1.00; transform: scale(1.14); }
        }
        @keyframes bar-shimmer {
          0%   { background-position: 200% center; }
          100% { background-position: -200% center; }
        }
        @keyframes msg-in {
          from { opacity: 0; transform: translateY(4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      {/* ── Splash overlay ──────────────────────────────────────────────────── */}
      <div style={{
        position:       "fixed",
        inset:          0,
        background:     "#000",
        display:        "flex",
        flexDirection:  "column",
        alignItems:     "center",
        justifyContent: "center",
        zIndex:         9999,
        opacity:        fadeOut ? 0 : 1,
        transition:     `opacity ${FADE_MS}ms cubic-bezier(0.4,0,0.2,1)`,
        overflow:       "hidden",
        userSelect:     "none",
      }}>

        {/* Ambient radial glow behind logo */}
        <div style={{
          position:      "absolute",
          inset:         0,
          background:    "radial-gradient(ellipse 60% 50% at 50% 48%, rgba(34,197,94,0.06) 0%, transparent 100%)",
          pointerEvents: "none",
        }} />

        {/* ── Logo ────────────────────────────────────────────────────────── */}
        <div style={{ position: "relative", marginBottom: 56 }}>
          {/* Animated glow halo */}
          <div style={{
            position:     "absolute",
            inset:        -28,
            borderRadius: "50%",
            background:   "radial-gradient(circle, rgba(34,197,94,0.20) 0%, transparent 68%)",
            animation:    "glow-pulse 2.4s ease-in-out infinite",
          }} />

          {/* Logo card */}
          <div style={{
            width:        96,
            height:       96,
            borderRadius: 24,
            background:   "linear-gradient(150deg, #141414 0%, #0c0c0c 100%)",
            border:       "1.5px solid rgba(34,197,94,0.22)",
            display:      "flex",
            flexDirection:"column",
            alignItems:   "center",
            justifyContent:"center",
            animation:    "logo-in 0.55s cubic-bezier(0.34,1.56,0.64,1) both",
            boxShadow:    "0 0 40px rgba(34,197,94,0.10), 0 0 12px rgba(34,197,94,0.06), inset 0 1px 0 rgba(255,255,255,0.04)",
          }}>
            <img
              src="/api/logo.svg"
              alt="Guardiola Farm 66"
              style={{ width: 64, height: 64, objectFit: "contain" }}
            />
          </div>
        </div>

        {/* ── Progress section ────────────────────────────────────────────── */}
        <div style={{
          width:         "min(268px, 80vw)",
          display:       "flex",
          flexDirection: "column",
          gap:           10,
        }}>
          {/* Top row: label + percentage */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{
              fontFamily: "system-ui",
              fontSize:   11,
              color:      "rgba(255,255,255,0.18)",
              letterSpacing: 0.4,
            }}>
              {welcome ? "Prêt ✓" : "Chargement"}
            </span>
            <span style={{
              fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', monospace",
              fontSize:   12,
              fontWeight: 600,
              color:      "#22c55e",
              minWidth:   34,
              textAlign:  "right",
            }}>
              {progress}%
            </span>
          </div>

          {/* Progress bar track */}
          <div style={{
            height:       3,
            background:   "rgba(255,255,255,0.07)",
            borderRadius: 999,
            overflow:     "hidden",
          }}>
            <div style={{
              height:      "100%",
              width:       `${progress}%`,
              borderRadius: 999,
              background:  "linear-gradient(90deg, #15803d, #22c55e 50%, #86efac)",
              backgroundSize: "200% 100%",
              boxShadow:   "0 0 12px rgba(34,197,94,0.65), 0 0 5px rgba(34,197,94,0.4)",
              animation:   progress > 0 && progress < 100
                ? "bar-shimmer 1.4s linear infinite"
                : "none",
              transition:  "width 0.04s linear",
            }} />
          </div>

          {/* Status message / Welcome */}
          <div style={{
            fontFamily:  "system-ui",
            fontSize:    12,
            color:       welcome ? "rgba(255,255,255,0.58)" : "rgba(255,255,255,0.32)",
            letterSpacing: 0.3,
            textAlign:   "center",
            minHeight:   18,
            transition:  "color 0.25s ease",
            animation:   "msg-in 0.2s ease both",
            // re-trigger animation on message change via key (handled by key prop below)
          }}>
            {welcome
              ? `👋 Bienvenue, ${FIRST_NAME}`
              : MESSAGES[msgIndex]}
          </div>
        </div>
      </div>
    </>
  );
}
