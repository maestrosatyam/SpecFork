import { animate, useMotionValue, useTransform, motion, useReducedMotion } from "framer-motion";
import { useEffect } from "react";

/** Animated percentage counter (0.92 -> "92%"). */
export function CountUpPct({ value, duration = 1.1, className }: { value: number; duration?: number; className?: string }) {
  const reduce = useReducedMotion();
  const mv = useMotionValue(reduce ? value * 100 : 0);
  const text = useTransform(mv, (v) => `${Math.round(v)}%`);
  useEffect(() => {
    if (reduce) {
      mv.set(value * 100);
      return;
    }
    const c = animate(mv, value * 100, { duration, ease: [0.2, 0.8, 0.2, 1] });
    return () => c.stop();
  }, [value, duration, mv, reduce]);
  return <motion.span className={className}>{text}</motion.span>;
}
