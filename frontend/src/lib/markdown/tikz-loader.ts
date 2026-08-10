/**
 * tikzjax (https://tikzjax.com) compiles a LaTeX/TikZ subset to SVG fully
 * in-browser via WASM - no server round-trip. It's a plain CDN script, not
 * an npm package (the npm release was unpublished), so this loads it once
 * and caches the promise; TikzBlock falls back to raw source if this
 * rejects or the render never completes (offline, CDN blocked, etc).
 */
let loadPromise: Promise<void> | null = null;

export function loadTikzJax(): Promise<void> {
  if (typeof window === "undefined") return Promise.reject(new Error("no window"));
  if (loadPromise) return loadPromise;

  loadPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>("script[data-tikzjax]");
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("failed to load tikzjax")));
      return;
    }
    const script = document.createElement("script");
    script.src = "https://tikzjax.com/v1/tikzjax.js";
    script.async = true;
    script.dataset.tikzjax = "true";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("failed to load tikzjax"));
    document.head.appendChild(script);
  });

  return loadPromise;
}

// tikzjax has no public API - its entire "scan the document for
// <script type=text/tikz> tags and compile each one to an inline <svg>"
// pass is wired up as a single `window.onload = async function() {...}`
// assignment (confirmed by reading its source directly: it's the only
// `window.*` property tikzjax touches). That's a fine trigger for a
// classic multi-page site where tikzjax's own <script> tag is present in
// the initial HTML and genuinely loads before the page's `load` event
// fires - it's a dead one here: this app loads tikzjax lazily, only once
// the first ```tikz block actually mounts, which in practice is always
// long after this SPA's real `window.onload` already fired once, on
// initial page load. The assignment still happens harmlessly (nothing
// else in this app uses `window.onload`), but the browser has no reason
// to ever invoke it again - so without calling it ourselves, an inserted
// <script type="text/tikz"> tag just sits there forever, un-processed,
// eventually hitting TikzBlock's own RENDER_TIMEOUT_MS fallback. Found by
// actually tracing a real render through devtools, not guessed - see
// tikz-block.tsx's comments for the rest of that story.
let renderChain: Promise<void> = Promise.resolve();

/** Kicks off tikzjax's scan-and-compile pass. Call this after inserting a
 * new `<script type="text/tikz">` tag (loadTikzJax() must have already
 * resolved, so `window.onload` is actually assigned by then).
 *
 * Queued through a single shared promise chain, not fired per call: the
 * WASM TeX engine tikzjax wraps is one instance with mutable global state
 * (it calls deleteEverything()/writeFile() before each compile) - it isn't
 * reentrant, so two overlapping invocations would corrupt each other's
 * output. Every TikzBlock on the page shares this same queue, so multiple
 * diagrams mounting around the same time still compile one at a time
 * instead of racing.
 */
export function triggerTikzRender(): void {
  renderChain = renderChain
    .then(async () => {
      const handler = window.onload as unknown as (() => unknown) | null;
      if (typeof handler === "function") await handler();
    })
    .catch(() => {
      // Swallowed - one failed compile shouldn't wedge the shared queue
      // for every other diagram waiting behind it. TikzBlock's own
      // RENDER_TIMEOUT_MS fallback is what surfaces this to the user.
    });
}
