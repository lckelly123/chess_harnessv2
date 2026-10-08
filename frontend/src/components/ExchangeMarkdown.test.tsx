import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ExchangeInput, ExchangeMarkdown } from "./ExchangeMarkdown";

describe("saved exchange presentation", () => {
  it("decodes JSON message strings once and renders their Markdown without changing the request", () => {
    const text = JSON.stringify({ model: "example", input: [
      { role: "developer", content: "# Instructions\n\nKeep **every** move.\nNext line." },
      { role: "user", content: "## Position\n\n- White to move\n- Literal code: `\\n`" },
    ], reasoning: { effort: "medium" }, store: false });
    const html = renderToStaticMarkup(<ExchangeInput text={text} />);
    expect(html).toContain("<h4>Instructions</h4>");
    expect(html).toContain("<strong>every</strong>");
    expect(html).toContain("move.\nNext line.");
    expect(html).toContain("<code>\\n</code>");
    expect(html).toContain("<li>White to move</li>");
    expect(html.indexOf("developer")).toBeLessThan(html.indexOf("user"));
    expect(html).toContain("&quot;reasoning&quot;");
    expect(html).toContain("&quot;store&quot;: false");
    expect(JSON.parse(text).input[0].content).toBe("# Instructions\n\nKeep **every** move.\nNext line.");
  });

  it("keeps multipart messages, tool calls, and unfamiliar request fields visible", () => {
    const html = renderToStaticMarkup(<ExchangeInput text={JSON.stringify({
      instructions: "Follow the board.",
      messages: [{ role: "user", name: "tester", content: [
        { type: "input_text", text: "## Legal moves\n\nRook e2: Rxe4", annotations: [] },
        { type: "input_image", image_url: "https://example.com/board.png" },
      ] }, { type: "function_call_output", call_id: "call-1", output: "exact tool result" }],
      tools: [{ type: "function", name: "inspect_square" }],
    })} />);
    for (const value of ["Follow the board.", "Legal moves", "Rook e2: Rxe4", "annotations", "tester", "input_image", "https://example.com/board.png", "call-1", "exact tool result", "inspect_square"]) {
      expect(html).toContain(value);
    }
    expect(html).not.toContain("<img");
  });

  it("renders Markdown inside literal model tags and never executes HTML or fetches images", () => {
    const html = renderToStaticMarkup(<ExchangeMarkdown text={'<running_thoughts>\n## Assessment\n\nA **hanging bishop**.\n</running_thoughts>\n\n<agent_tool_calls>\n[{"tool":"inspect_square"}]\n</agent_tool_calls>\n\n<script>alert("x")</script>\n\n![board](https://example.com/board.png)\n\n[unsafe](javascript:alert%281%29)'} />);
    expect(html).toContain("<h4>Assessment</h4>");
    expect(html).toContain("<strong>hanging bishop</strong>");
    expect(html).toContain("&lt;running_thoughts&gt;");
    expect(html).toContain("&lt;/running_thoughts&gt;");
    expect(html).toContain("inspect_square");
    expect(html).not.toMatch(/<script|<img|href="javascript:/);
    expect(html).toContain("![board](https://example.com/board.png)");
  });

  it("supports tables and code while keeping plain-text and unfamiliar JSON inputs readable", () => {
    const html = renderToStaticMarkup(<ExchangeMarkdown text={"| Piece | Move |\n| --- | --- |\n| Rook | Rxe4 |\n\n```json\n{\"move\": \"Rxe4\"}\n```"} />);
    expect(html).toContain("<table>");
    expect(html).toContain("<th>Piece</th>");
    expect(html).toContain('<code class="language-json">');
    expect(renderToStaticMarkup(<ExchangeInput text={"## Plain prompt\n\nKeep this."} />)).toContain("<h4>Plain prompt</h4>");
    expect(renderToStaticMarkup(<ExchangeInput text='{"unknown":"keep me"}' />)).toContain("&quot;unknown&quot;: &quot;keep me&quot;");
  });
});
