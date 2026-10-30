import { GITHUB_URL } from "../config";
import { useLabels } from "../lib/models";
import type { Health } from "../types";
import { IconGithub } from "./Icons";
import { LogoGlyph, Wordmark } from "./Logo";

export function Header({
  onHome,
  onHowItWorks,
  mode,
  health = null,
}: {
  onHome: () => void;
  onHowItWorks: () => void;
  mode: "live" | "mock" | null;
  health?: Health | null;
}) {
  const labels = useLabels();
  return (
    <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-ink-900/80 backdrop-blur-md">
      <div className="mx-auto flex h-[68px] max-w-[1600px] items-center gap-4 px-4 sm:px-6 lg:px-10">
        <a
          href="#/"
          onClick={(e) => {
            e.preventDefault();
            onHome();
          }}
          className="flex shrink-0 items-center gap-3 rounded-lg"
          aria-label="SpecFork home"
        >
          <LogoGlyph />
          <Wordmark />
        </a>
        <p className="hidden min-w-0 truncate border-l border-white/10 pl-4 text-[14.5px] text-fog-400 lg:block">
          Your spec means more than one thing. Find out which, before your coding agent guesses.
        </p>
        <div className="ml-auto flex shrink-0 items-center gap-1 sm:gap-2 [&>*]:shrink-0 [&>*]:whitespace-nowrap">
          {mode === "mock" && (
            <span
              className="chip hidden border-warn/30 bg-warn/10 text-warn sm:inline-flex"
              title="No backend reachable (or ?mock=1): showing a recorded fixture with simulated timing."
            >
              <span className="h-1.5 w-1.5 rounded-full bg-warn" /> Demo data
            </span>
          )}
          <SandboxBadge sandbox={health?.sandbox} />
          <span className="chip hidden xl:inline-flex" title={`Fast: ${labels.fast} · Deep: ${labels.deep}`}>
            <span className="h-1.5 w-1.5 rounded-full bg-[#76b900]" aria-hidden />
            Powered by {labels.family} on {labels.provider}
          </span>
          <button type="button" className="btn btn-quiet" onClick={onHowItWorks}>
            How it works
          </button>
          <a className="btn btn-quiet" href={GITHUB_URL} target="_blank" rel="noreferrer" aria-label="SpecFork on GitHub">
            <IconGithub />
            <span className="hidden sm:inline">GitHub</span>
          </a>
        </div>
      </div>
    </header>
  );
}

/** Sandbox strength: loud amber when code runs without network isolation, a quiet green dot when it is isolated. */
export function SandboxBadge({ sandbox }: { sandbox?: Health["sandbox"] }) {
  if (!sandbox) return null;
  if (sandbox.net_isolated === false)
    return (
      <span
        className="chip border-warn/40 bg-warn/10 text-warn"
        title="Generated code runs in a resource-limited sandbox, but without network isolation on this host. Don't submit specs whose implementations could do anything sensitive."
        aria-label="Sandbox: weak isolation. Generated code runs without network isolation on this host."
        role="status"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-warn" aria-hidden />
        Sandbox: weak isolation
      </span>
    );
  if (sandbox.net_isolated === true)
    return (
      <span
        className="hidden items-center gap-1.5 px-1 text-[12px] text-fog-500 lg:inline-flex"
        title="Generated code runs in a sandbox with no network access."
      >
        <span className="h-1.5 w-1.5 rounded-full bg-add/80" aria-hidden />
        Sandbox: isolated
      </span>
    );
  return null;
}
