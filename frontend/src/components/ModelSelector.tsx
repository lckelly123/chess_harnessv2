import { Cpu, RefreshCw, Server } from "lucide-react";
import { useEffect, useState } from "react";
import { matchApi } from "../api/client";
import type { LocalModelServer, ModelSelection } from "../api/contracts";

interface ModelSelectorProps {
  selection: ModelSelection;
  disabled: boolean;
  onChange: (selection: ModelSelection) => void;
  onReadyChange: (ready: boolean) => void;
}

interface Inventory {
  server: LocalModelServer;
  models: string[];
  error: string | null;
}

export function ModelSelector({ selection, disabled, onChange, onReadyChange }: ModelSelectorProps) {
  const server = selection.modelId === "gpt-terra" ? "openai" : selection.modelId === "unsloth" ? "unsloth" : "lmstudio";
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [revision, setRevision] = useState(0);
  const local = server !== "openai";
  const current = inventory?.server === server ? inventory : null;
  const loading = local && !current;
  const selectedModel = selection.modelName ?? (current?.models.length === 1 ? current.models[0] : "");
  const ready = !local || (!!current && !current.error && current.models.includes(selectedModel));

  useEffect(() => {
    if (server === "openai") return;
    let cancelled = false;
    matchApi.listLoadedModels(server).then(
      (result) => { if (!cancelled) setInventory({ ...result, error: null }); },
      (error: unknown) => {
        if (!cancelled) setInventory({ server, models: [], error: error instanceof Error ? error.message : "Model server unavailable. Refresh to reconnect." });
      },
    );
    return () => { cancelled = true; };
  }, [server, revision]);

  useEffect(() => {
    if (local && current?.models.length === 1 && !selection.modelName) {
      onChange({ ...selection, modelName: current.models[0] });
    }
  }, [local, current, selection, onChange]);

  useEffect(() => { onReadyChange(ready); }, [ready, server, onReadyChange]);

  const refresh = () => {
    setInventory(null);
    setRevision((value) => value + 1);
  };
  const unavailable = !!selection.modelName && !!current && !current.models.includes(selection.modelName);
  const status = !local ? "OpenAI API" : loading ? "Checking loaded models…"
    : current?.error ?? (!current?.models.length ? "No model loaded. Load one in your server, then refresh."
      : unavailable ? "Selected model is no longer loaded. Choose a model or refresh."
        : !ready ? "Choose a loaded model to run."
          : `${server === "unsloth" ? "Unsloth" : "LM Studio"} · ${current.models.length} loaded`);

  return (
    <section className="model-settings" aria-labelledby="model-settings-title">
      <h2 id="model-settings-title"><Cpu size={18} aria-hidden="true" /> Model</h2>
      <label className="model-settings__field">
        <span>Server</span>
        <select
          value={selection.modelId}
          disabled={disabled}
          aria-label="Model server"
          onChange={(event) => {
            const modelId = event.target.value as ModelSelection["modelId"];
            if (modelId === selection.modelId) return;
            setInventory(null);
            onReadyChange(false);
            onChange({ modelId, reasoningEffort: "medium" });
          }}
        >
          <option value="qwen">LM Studio</option>
          <option value="unsloth">Unsloth</option>
          <option value="gpt-terra">OpenAI</option>
        </select>
      </label>
      <label className="model-settings__field model-settings__loaded">
        <span>{local ? "Loaded model" : "Requested model"}</span>
        <select value={local ? selectedModel : "gpt-terra"} title={local ? selectedModel : "GPT Terra"}
          disabled={disabled || loading || (local && !current?.models.length) || !local}
          aria-label={local ? "Loaded model" : "Requested model"} aria-describedby="model-routing-status"
          onChange={(event) => onChange({ ...selection, modelName: event.target.value || undefined })}>
          {!local ? <option value="gpt-terra">GPT Terra</option> : <>
            <option value="" disabled>{loading ? "Loading…" : !current?.models.length ? "No loaded models" : "Choose a model"}</option>
            {unavailable && selection.modelName ? <option value={selection.modelName} disabled>{selection.modelName} (unavailable)</option> : null}
            {current?.models.map((model) => <option key={model} value={model}>{model}</option>)}
          </>}
        </select>
      </label>
      <dl className="model-settings__reasoning">
        <div><dt>Reasoning</dt><dd>Medium</dd></div>
      </dl>
      <div className="model-settings__connection">
        <p id="model-routing-status" className={`model-settings__status${current?.error || unavailable ? " model-settings__status--error" : ""}`} role="status">
          <Server size={15} aria-hidden="true" /><span>{status}</span>
        </p>
        {local ? <button className="model-settings__refresh" type="button" disabled={disabled || loading} onClick={refresh} aria-label="Refresh loaded models">
          <RefreshCw size={14} aria-hidden="true" /> Refresh
        </button> : null}
      </div>
    </section>
  );
}
