import { useEffect, useMemo, useState } from "react";
import { detectApi, type Api } from "./api";
import { Composer } from "./components/Composer";
import { Header } from "./components/Header";
import { HowItWorksModal } from "./components/HowItWorks";
import { RunView } from "./components/RunView";
import { LabelsContext, labelsFromHealth } from "./lib/models";
import { runHash, useHashRoute } from "./lib/route";
import type { Health, Preset, RunSummary } from "./types";

export function App() {
  const [api, setApi] = useState<Api | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [route, go] = useHashRoute();
  const [presets, setPresets] = useState<Preset[] | null>(null);
  const [presetsError, setPresetsError] = useState<string | null>(null);
  const [recent, setRecent] = useState<RunSummary[]>([]);
  const [howOpen, setHowOpen] = useState(false);
  const [draft, setDraft] = useState<{ spec: string; key: number }>({ spec: "", key: 0 });
  const labels = useMemo(() => labelsFromHealth(health), [health]);

  useEffect(() => {
    detectApi().then(({ api, health }) => {
      setApi(api);
      setHealth(health);
    });
  }, []);

  useEffect(() => {
    if (!api) return;
    api
      .presets()
      .then(setPresets)
      .catch((e) => setPresetsError(e?.detail ?? e?.message ?? "error"));
  }, [api]);

  useEffect(() => {
    if (!api || route.name !== "home") return;
    api
      .listRuns()
      .then(setRecent)
      .catch(() => setRecent([]));
  }, [api, route.name]);

  useEffect(() => {
    document.title = route.name === "run" ? "SpecFork: run" : "SpecFork: find the meanings hiding in your spec";
  }, [route]);

  return (
    <LabelsContext.Provider value={labels}>
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-lg focus:bg-fog-50 focus:px-3 focus:py-2 focus:text-ink-900">
        Skip to content
      </a>
      <Header onHome={() => go("#/")} onHowItWorks={() => setHowOpen(true)} mode={api?.mode ?? null} health={health} />
      <div id="main">
        {!api ? (
          <div className="flex h-[60vh] items-center justify-center" aria-busy="true">
            <span className="h-8 w-8 animate-spin rounded-full border-2 border-white/15 border-t-fog-100" aria-label="Connecting" />
          </div>
        ) : route.name === "run" ? (
          <RunView
            key={route.id}
            api={api}
            id={route.id}
            onHome={() => go("#/")}
            onForkSpec={(spec) => {
              setDraft((d) => ({ spec, key: d.key + 1 }));
              go("#/");
            }}
          />
        ) : (
          <Composer
            key={draft.key}
            api={api}
            presets={presets}
            presetsError={presetsError}
            recent={recent}
            initialSpec={draft.spec}
            health={health}
            liveDisabled={api.mode === "live" && health?.llm_configured === false}
            onCreated={(id) => go(runHash(id))}
            onOpenRun={(id) => go(runHash(id))}
          />
        )}
      </div>
      <footer className="border-t border-white/[0.06] py-8 text-center text-[13px] text-fog-500">
        SpecFork · built for the Nebius × NVIDIA Global AI Hackathon 2026 · inference by {labels.family} on {labels.provider}
      </footer>
      <HowItWorksModal open={howOpen} onClose={() => setHowOpen(false)} />
    </div>
    </LabelsContext.Provider>
  );
}
