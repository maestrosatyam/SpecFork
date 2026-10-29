import { Highlight, type PrismTheme } from "prism-react-renderer";
import { useState } from "react";
import { IconCheck, IconCopy } from "./Icons";

const theme: PrismTheme = {
  plain: { color: "#dfe5f2", backgroundColor: "transparent" },
  styles: [
    { types: ["comment", "prolog", "doctype", "cdata"], style: { color: "#6f7ca0", fontStyle: "italic" } },
    { types: ["string", "char", "attr-value", "triple-quoted-string"], style: { color: "#9fe0b9" } },
    { types: ["number", "boolean", "constant"], style: { color: "#F5B86B" } },
    { types: ["keyword", "builtin"], style: { color: "#b9a6ff" } },
    { types: ["function", "class-name"], style: { color: "#7cc8f2" } },
    { types: ["operator", "punctuation"], style: { color: "#98a3bf" } },
    { types: ["decorator", "annotation"], style: { color: "#E68AC0" } },
  ],
};

export function CodeBlock({
  code,
  language = "python",
  maxHeight,
  showLineNumbers = true,
  className = "",
  label,
}: {
  code: string;
  language?: string;
  maxHeight?: number | string;
  showLineNumbers?: boolean;
  className?: string;
  label?: string;
}) {
  return (
    <Highlight code={code.replace(/\n$/, "")} language={language} theme={theme}>
      {({ tokens, getLineProps, getTokenProps }) => (
        <pre
          className={`mono scroll-thin overflow-auto rounded-xl border border-white/[0.06] bg-ink-950/70 py-3.5 text-[13.5px] leading-[1.65] ${className}`}
          style={{ maxHeight }}
          aria-label={label}
          tabIndex={0}
        >
          {tokens.map((line, i) => {
            const { key: _k, ...lineProps } = getLineProps({ line, key: i }) as Record<string, unknown>;
            void _k;
            return (
              <div key={i} {...(lineProps as object)} className="flex px-4">
                {showLineNumbers && (
                  <span className="mr-4 inline-block w-6 shrink-0 select-none text-right text-fog-500/60">{i + 1}</span>
                )}
                <span className="whitespace-pre">
                  {line.map((token, k) => {
                    const { key: _tk, ...tp } = getTokenProps({ token, key: k }) as Record<string, unknown>;
                    void _tk;
                    return <span key={k} {...(tp as object)} />;
                  })}
                </span>
              </div>
            );
          })}
        </pre>
      )}
    </Highlight>
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
