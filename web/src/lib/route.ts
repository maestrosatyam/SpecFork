import { useEffect, useState } from "react";

export type Route = { name: "home" } | { name: "run"; id: string };

export function parseHash(hash: string): Route {
  const m = hash.match(/^#\/run\/([^/?#]+)/);
  if (m) return { name: "run", id: decodeURIComponent(m[1]) };
  return { name: "home" };
}

export function runHash(id: string): string {
  return `#/run/${encodeURIComponent(id)}`;
}

export function useHashRoute(): [Route, (hash: string) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = (hash: string) => {
    if (window.location.hash !== hash) window.location.hash = hash;
    else setRoute(parseHash(hash));
    window.scrollTo({ top: 0 });
  };
  return [route, go];
}
