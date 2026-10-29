// Word-level diff (LCS) used to highlight what the clarified spec added.

export type DiffSeg = { type: "same" | "add" | "del"; text: string };

/** Split into words and the whitespace that follows them, so joining segments reproduces the text. */
export function tokenize(s: string): string[] {
  return s.match(/\s+|[^\s]+/g) ?? [];
}

function norm(tok: string): string {
  return /^\s+$/.test(tok) ? " " : tok.toLowerCase().replace(/[.,;:!?]+$/, "");
}

/**
 * Diff `before` -> `after` at word granularity. Whitespace tokens are matched loosely.
 * Adjacent segments of the same type are merged. O(n*m) – fine for specs (< ~600 words).
 */
export function wordDiff(before: string, after: string): DiffSeg[] {
  const a = tokenize(before);
  const b = tokenize(after);
  const n = a.length;
  const m = b.length;
  const na = a.map(norm);
  const nb = b.map(norm);
  // dp[i][j] = LCS length of a[i:], b[j:]
  const dp: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = na[i] === nb[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffSeg[] = [];
  const push = (type: DiffSeg["type"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.type === type) last.text += text;
    else out.push({ type, text });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (na[i] === nb[j]) {
      push("same", b[j]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push("del", a[i]);
      i++;
    } else {
      push("add", b[j]);
      j++;
    }
  }
  while (i < n) push("del", a[i++]);
  while (j < m) push("add", b[j++]);
  // Whitespace-only add/del segments are noise; fold them into "same".
  const cleaned: DiffSeg[] = [];
  for (const seg of out) {
    if (seg.type !== "same" && /^\s*$/.test(seg.text)) {
      if (seg.type === "del") continue;
      const last = cleaned[cleaned.length - 1];
      if (last && last.type === "same") last.text += seg.text;
      else cleaned.push({ type: "same", text: seg.text });
      continue;
    }
    const last = cleaned[cleaned.length - 1];
    if (last && last.type === seg.type) last.text += seg.text;
    else cleaned.push({ ...seg });
  }
  return cleaned;
}

/** Share of words in `after` that are new. */
export function addedWordCount(segs: DiffSeg[]): number {
  return segs.filter((s) => s.type === "add").reduce((acc, s) => acc + (s.text.match(/\S+/g)?.length ?? 0), 0);
}
