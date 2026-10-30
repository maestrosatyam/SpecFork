import { lazy, Suspense, useState } from "react";
import { IconCheck, IconCopy } from "./Icons";

export type CodeBlockProps = {
  code: string;
  language?: string;
  maxHeight?: number | string;
  showLineNumbers?: boolean;
  className?: string;
  label?: string;
};

const HighlightedCode = lazy(() => import("./HighlightedCode"));

/** Same box as the highlighted version, unstyled tokens: shown while the highlighter chunk loads. */
function PlainCode({ code, maxHeight, showLineNumbers = true, className = "", label }: CodeBlockProps) {
  const lines = code.replace(/\n$/, "").split("\n");
  return (
    <pre
      className={`mono scroll-thin overflow-auto rounded-xl border border-white/[0.06] bg-ink-950/70 py-3.5 text-[13.5px] leading-[1.65] text-[#dfe5f2] ${className}`}
      style={{ maxHeight }}
      aria-label={label}
      tabIndex={0}
    >
      {lines.map((line, i) => (
        <div key={i} className="flex px-4">
          {showLineNumbers && <span className="mr-4 inline-block w-6 shrink-0 select-none text-right text-fog-500/60">{i + 1}</span>}
          <span className="whitespace-pre">{line}</span>
        </div>
      ))}
    </pre>
  );
}

export function CodeBlock(props: CodeBlockProps) {
  return (
    <Suspense fallback={<PlainCode {...props} />}>
      <HighlightedCode {...props} />
    </Suspense>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-ghost px-3 py-1.5 text-[13px]"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
        } catch {
          const ta = document.createElement("textarea");
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          ta.remove();
        }
        setDone(true);
        window.setTimeout(() => setDone(false), 1400);
      }}
      aria-live="polite"
    >
      {done ? <IconCheck size={15} /> : <IconCopy size={15} />}
      {done ? "Copied" : label}
    </button>
  );
}
