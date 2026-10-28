// Word-level diff for the revision history (plan Section 11.3 "Must":
// history and revision diff). Pure and dependency-free: a longest-common-
// subsequence table over word tokens, collapsed into runs.

export type DiffToken = { op: "same" | "add" | "del"; text: string };

function tokenize(text: string): string[] {
  // keep the whitespace with the words so the rendered diff reads naturally
  return text.split(/(\s+)/).filter((t) => t.length > 0);
}

export function diffWords(before: string, after: string): DiffToken[] {
  const a = tokenize(before);
  const b = tokenize(after);
  const n = a.length;
  const m = b.length;

  // dp[i][j] = LCS length of a[i:] and b[j:]
  const dp: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const out: DiffToken[] = [];
  const push = (op: DiffToken["op"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.op === op) last.text += text;
    else out.push({ op, text });
  };

  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      push("same", a[i]);
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
  return out;
}

/** Word counts for the "+n / −m" summary line. */
export function diffSummary(tokens: DiffToken[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const t of tokens) {
    const words = t.text.split(/\s+/).filter(Boolean).length;
    if (t.op === "add") added += words;
    if (t.op === "del") removed += words;
  }
  return { added, removed };
}
