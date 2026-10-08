import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { matchApi } from "../api/client";
import type { ModelPassExchange } from "../api/contracts";
import { ModelExchangeContext } from "./modelExchangeContext";
import { ExchangeInput, ExchangeMarkdown } from "./ExchangeMarkdown";

const route = () => {
  const match = /^#model-pass\/([0-9a-f-]{36})\/([1-9]\d*)$/i.exec(window.location.hash);
  return match ? { runId: match[1], passNumber: Number(match[2]) } : null;
};
const message = (error: unknown) => error instanceof Error ? error.message : "The saved model exchange could not be loaded.";

export function ModelExchangeViewer({ children }: { children: ReactNode }) {
  const [exchange, setExchange] = useState<ModelPassExchange | null>(null);
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const navigation = useRef(0);
  const returnTo = useRef<{ focus: HTMLElement | null; scrollY: number }>({ focus: null, scrollY: 0 });

  const restore = useCallback(() => {
    setExchange(null);
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: returnTo.current.scrollY, behavior: "instant" });
      returnTo.current.focus?.focus({ preventScroll: true });
    });
  }, []);

  const back = useCallback(() => {
    if (!route()) return;
    ++navigation.current;
    if (window.history.state?.modelExchange) window.history.back();
    else {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      restore();
    }
  }, [restore]);

  const open = useCallback(async (runId: string, passNumber: number) => {
    const version = ++navigation.current;
    const origin = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const data = await matchApi.getModelPassExchange(runId, passNumber);
    // Don't open a stale request after the user has left the originating view.
    if (version !== navigation.current || (origin && (!origin.isConnected || origin.closest("[hidden]")))) return;
    returnTo.current = { focus: origin, scrollY: window.scrollY };
    window.history.pushState({ modelExchange: true }, "", `#model-pass/${runId}/${passNumber}`);
    setNavigationError(null);
    setExchange(data);
  }, []);

  useEffect(() => {
    let disposed = false;
    const originalRestoration = window.history.scrollRestoration;
    window.history.scrollRestoration = "manual";
    const navigate = async () => {
      const version = ++navigation.current;
      const target = route();
      if (!target) { restore(); return; }
      try {
        const data = await matchApi.getModelPassExchange(target.runId, target.passNumber);
        if (!disposed && version === navigation.current) { setNavigationError(null); setExchange(data); }
      } catch (caught) {
        if (disposed || version !== navigation.current) return;
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
        restore();
        setNavigationError(`Could not expand this pass. ${message(caught)} Return to its pass card and try Expand again.`);
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || !route()) return;
      event.preventDefault();
      back();
    };
    window.addEventListener("popstate", navigate);
    window.addEventListener("keydown", escape);
    if (route()) void navigate();
    return () => {
      disposed = true;
      window.history.scrollRestoration = originalRestoration;
      window.removeEventListener("popstate", navigate);
      window.removeEventListener("keydown", escape);
    };
  }, [back, restore]);

  useEffect(() => {
    if (exchange) {
      window.scrollTo({ top: 0, behavior: "instant" });
      heading.current?.focus({ preventScroll: true });
    }
  }, [exchange]);

  return (
    <ModelExchangeContext.Provider value={open}>
      <div hidden={exchange !== null}>
        {navigationError ? <p className="model-exchange-error" role="alert">{navigationError}</p> : null}
        {children}
      </div>
      {exchange ? <main className="model-exchange-view">
        <div className="model-exchange-toolbar">
          <button className="button button--secondary model-exchange-back" type="button" aria-label="Back to previous view" onClick={back}><ArrowLeft size={18} aria-hidden="true" />Back</button>
        </div>
        <section className="model-exchange-section" aria-labelledby="model-input-heading">
          <h1 id="model-input-heading" ref={heading} tabIndex={-1}>Input:</h1>
          <ExchangeInput text={exchange.input} />
        </section>
        <section className="model-exchange-section" aria-labelledby="model-output-heading">
          <h2 id="model-output-heading">Output:</h2>
          {exchange.output.map((block, index) => <ExchangeMarkdown key={index} text={block} />)}
        </section>
      </main> : null}
    </ModelExchangeContext.Provider>
  );
}
