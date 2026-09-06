import { FolderPlus, Play, X } from "lucide-react";
import { useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import type { GameFolder, HarnessVersion } from "../api/contracts";

interface MatchDocketProps {
  harnesses: HarnessVersion[];
  whiteId: string;
  blackId: string;
  folders: GameFolder[];
  folderId: string;
  busy: boolean;
  folderBusy: boolean;
  folderError: string | null;
  onWhiteChange(value: string): void;
  onBlackChange(value: string): void;
  onFolderChange(value: string): void;
  onCreateFolder(name: string): Promise<boolean>;
  onStart(): void;
}

export function MatchDocket({
  harnesses,
  whiteId,
  blackId,
  folders,
  folderId,
  busy,
  folderBusy,
  folderError,
  onWhiteChange,
  onBlackChange,
  onFolderChange,
  onCreateFolder,
  onStart,
}: MatchDocketProps) {
  const [addingFolder, setAddingFolder] = useState(false);
  const [folderName, setFolderName] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    onStart();
  };

  const createFolder = async () => {
    const normalized = folderName.trim();
    if (!normalized) return;
    const created = await onCreateFolder(normalized);
    if (!created) return;
    setFolderName("");
    setAddingFolder(false);
  };

  const handleFolderKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void createFolder();
    }
    if (event.key === "Escape") {
      setAddingFolder(false);
      setFolderName("");
    }
  };
  return (
    <form className="match-docket" onSubmit={submit}>
      <div className="docket-title">
        <span className="docket-number">NEW MATCH</span>
        <p>Choose two versioned harnesses. The backend validates and records every move.</p>
      </div>
      <label className="field-control">
        <span>White harness</span>
        <select value={whiteId} onChange={(event) => onWhiteChange(event.target.value)} disabled={busy}>
          {harnesses.map((harness) => (
            <option key={harness.id} value={harness.id}>
              {harness.name} · {harness.version}
            </option>
          ))}
        </select>
      </label>
      <span className="versus-mark" aria-hidden="true">vs</span>
      <label className="field-control">
        <span>Black harness</span>
        <select value={blackId} onChange={(event) => onBlackChange(event.target.value)} disabled={busy}>
          {harnesses.map((harness) => (
            <option key={harness.id} value={harness.id}>
              {harness.name} · {harness.version}
            </option>
          ))}
        </select>
      </label>
      <div className="field-control folder-field">
        <span id="game-folder-label">Game folder</span>
        <div className="docket-folder-picker">
          <select
            value={folderId}
            aria-labelledby="game-folder-label"
            onChange={(event) => onFolderChange(event.target.value)}
            disabled={busy || folderBusy}
          >
            <option value="">Unfiled</option>
            {folders.map((folder) => (
              <option key={folder.id} value={folder.id}>{folder.name}</option>
            ))}
          </select>
          <button
            type="button"
            aria-expanded={addingFolder}
            onClick={() => setAddingFolder((value) => !value)}
          >
            {addingFolder ? <X size={14} aria-hidden="true" /> : <FolderPlus size={14} aria-hidden="true" />}
            {addingFolder ? "Cancel" : "New"}
          </button>
        </div>
        {addingFolder ? (
          <div className="docket-folder-create">
            <label className="sr-only" htmlFor="new-match-folder-name">New folder name</label>
            <input
              id="new-match-folder-name"
              value={folderName}
              maxLength={60}
              placeholder="Folder name"
              autoFocus
              disabled={folderBusy}
              onChange={(event) => setFolderName(event.target.value)}
              onKeyDown={handleFolderKeyDown}
            />
            <button type="button" disabled={folderBusy || !folderName.trim()} onClick={() => void createFolder()}>
              {folderBusy ? "Saving…" : "Create folder"}
            </button>
          </div>
        ) : null}
        {addingFolder && folderError ? <p className="docket-folder-error" role="alert">{folderError}</p> : null}
      </div>
      <div className="docket-actions">
        <button className="button button--primary" type="submit" disabled={busy || !whiteId || !blackId}>
          <Play size={16} strokeWidth={2} aria-hidden="true" />
          {busy ? "Starting…" : "Start match"}
        </button>
      </div>
    </form>
  );
}
