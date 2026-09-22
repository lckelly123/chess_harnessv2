import { Cpu, Server } from "lucide-react";
import type { ModelSelection } from "../api/contracts";

interface ModelSelectorProps {
  selection: ModelSelection;
  disabled: boolean;
  onChange: (selection: ModelSelection) => void;
}

export function ModelSelector({ selection, disabled, onChange }: ModelSelectorProps) {
  return (
    <section className="model-settings" aria-labelledby="model-settings-title">
      <h2 id="model-settings-title"><Cpu size={18} aria-hidden="true" /> Model</h2>
      <label className="model-settings__field">
        <span>Requested model</span>
        <select
          value={selection.modelId}
          disabled={disabled}
          aria-label="Requested model"
          aria-describedby="model-routing-status"
          onChange={(event) => onChange({
            modelId: event.target.value as ModelSelection["modelId"],
            reasoningEffort: "medium",
          })}
        >
          <option value="qwen">Qwen</option>
          <option value="gpt-terra">GPT Terra</option>
        </select>
      </label>
      <dl className="model-settings__reasoning">
        <div><dt>Reasoning</dt><dd>Medium</dd></div>
      </dl>
      <p id="model-routing-status" className="model-settings__status">
        <Server size={15} aria-hidden="true" />
        <span>{selection.modelId === "gpt-terra" ? "OpenAI API" : "LM Studio"}</span>
      </p>
    </section>
  );
}
