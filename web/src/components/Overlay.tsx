import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, type ReactNode } from "react";
import { IconX } from "./Icons";

function useOverlayBehaviour(open: boolean, onClose: () => void, panelRef: React.RefObject<HTMLDivElement | null>) {
  // Keep the latest onClose without re-running the effect (parents re-render on every live snapshot).
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
      }
      if (e.key === "Tab" && panelRef.current) {
        const f = panelRef.current.querySelectorAll<HTMLElement>(
          'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])',
        );
        if (!f.length) return;
        const first = f[0];
        const last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.setTimeout(() => panelRef.current?.focus(), 30);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      prev?.focus?.();
    };
  }, [open, panelRef]);
}

export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  width = 880,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  width?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useOverlayBehaviour(open, onClose, ref);
  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50">
          <motion.div
            className="absolute inset-0 bg-ink-950/70 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            ref={ref}
            role="dialog"
            aria-modal="true"
            aria-label={typeof title === "string" ? title : undefined}
            tabIndex={-1}
            className="absolute right-0 top-0 flex h-full w-full flex-col border-l border-white/10 bg-ink-850 shadow-2xl outline-none"
            style={{ maxWidth: width }}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 40 }}
          >
            <div className="flex items-start justify-between gap-4 border-b border-white/[0.07] px-6 py-5">
              <div className="min-w-0">
                <h2 className="font-display text-[22px] font-semibold text-fog-50">{title}</h2>
                {subtitle && <div className="mt-1 text-[14px] text-fog-400">{subtitle}</div>}
              </div>
              <button type="button" className="btn btn-quiet -mr-2" onClick={onClose} aria-label="Close panel">
                <IconX size={20} />
              </button>
            </div>
            <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useOverlayBehaviour(open, onClose, ref);
  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            className="absolute inset-0 bg-ink-950/75 backdrop-blur-[3px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            ref={ref}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            tabIndex={-1}
            className="card scroll-thin relative max-h-[90vh] w-full max-w-[1040px] overflow-y-auto bg-ink-850 p-6 outline-none sm:p-8"
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
          >
            <div className="mb-6 flex items-start justify-between gap-4">
              <h2 className="font-display text-[26px] font-semibold tracking-tight text-fog-50">{title}</h2>
              <button type="button" className="btn btn-quiet -mr-2 -mt-1" onClick={onClose} aria-label="Close">
                <IconX size={20} />
              </button>
            </div>
            {children}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
