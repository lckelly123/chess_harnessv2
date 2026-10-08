import { createElement } from "react";
import Markdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type {} from "remark-parse";
import type { Plugin } from "unified";

// Model tags are source text, never HTML. Disabling HTML parsing also lets
// Markdown inside <think> and <running_thoughts> render normally.
const literalHtml: Plugin = function () {
  const data = this.data();
  const extensions = data.micromarkExtensions ?? (data.micromarkExtensions = []);
  extensions.push({ disable: { null: ["htmlFlow", "htmlText"] } });
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function JsonContent({ value }: { value: unknown }) {
  return <pre className="model-exchange-json"><code>{JSON.stringify(value, null, 2)}</code></pre>;
}

export function ExchangeMarkdown({ text, headingOffset = 2 }: { text: string; headingOffset?: number }) {
  const components: Components = {
    a: ({ children, href, title }) => <a href={href} title={title} target="_blank" rel="noreferrer">{children}</a>,
    // Inspect image references as text instead of fetching model-authored URLs.
    img: ({ alt, src, title }) => <code>{`![${alt ?? ""}](${src ?? ""}${title ? ` "${title}"` : ""})`}</code>,
    table: ({ children }) => <div className="model-exchange-table" tabIndex={0} role="region" aria-label="Scrollable table"><table>{children}</table></div>,
  };
  for (const level of [1, 2, 3, 4, 5, 6] as const) {
    components[`h${level}`] = ({ children }) => createElement(`h${Math.min(6, level + headingOffset)}`, null, children);
  }
  return <div className="model-exchange-markdown"><Markdown remarkPlugins={[remarkGfm, literalHtml]} components={components}>{text}</Markdown></div>;
}

function InputContent({ value }: { value: unknown }) {
  if (typeof value === "string") return <ExchangeMarkdown text={value} headingOffset={3} />;
  if (Array.isArray(value)) return <>{value.map((part, index) => <InputContent key={index} value={part} />)}</>;
  if (isRecord(value)) {
    if (typeof value.role === "string" && (typeof value.content === "string" || Array.isArray(value.content))) {
      const { role, content, ...details } = value;
      return <div className="model-exchange-message">
        <h3 className="model-exchange-role">{role}</h3>
        <InputContent value={content} />
        {Object.keys(details).length ? <JsonContent value={details} /> : null}
      </div>;
    }
    if (["text", "input_text", "output_text"].includes(String(value.type)) && typeof value.text === "string") {
      const { text, ...details } = value;
      return <><ExchangeMarkdown text={text} headingOffset={3} /><JsonContent value={details} /></>;
    }
  }
  return <JsonContent value={value} />;
}

export function ExchangeInput({ text }: { text: string }) {
  let request: unknown;
  try { request = JSON.parse(text); }
  catch { return <ExchangeMarkdown text={text} />; }
  if (!isRecord(request)) return <JsonContent value={request} />;

  const promptFields = new Set(["instructions", "input", "messages"]);
  const prompts = Object.entries(request).filter(([key]) => promptFields.has(key));
  const settings = Object.fromEntries(Object.entries(request).filter(([key]) => !promptFields.has(key)));
  if (!prompts.length) return <JsonContent value={request} />;

  return <>
    {prompts.map(([key, value]) => <div className="model-exchange-prompt" key={key}>
      {key === "instructions" ? <h3 className="model-exchange-role">Instructions</h3> : null}
      <InputContent value={value} />
    </div>)}
    {Object.keys(settings).length ? <JsonContent value={settings} /> : null}
  </>;
}
