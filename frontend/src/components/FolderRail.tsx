import { Folder, FolderOpen, FolderPlus, X } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import type { GameFolder } from "../api/contracts";

interface FolderRailProps {
  folders: GameFolder[];
  totalMatches: number;
  unfiledCount: number;
  selectedId: string;
  creating: boolean;
  createError: string | null;
  onSelect(folderId: string): void;
  onCreate(name: string): Promise<boolean>;
}

export function FolderRail({
  folders,
  totalMatches,
  unfiledCount,
  selectedId,
  creating,
  createError,
  onSelect,
  onCreate,
}: FolderRailProps) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const normalized = name.trim();
    if (!normalized) return;
    const created = await onCreate(normalized);
    if (!created) return;
    setName("");
    setAdding(false);
  };

  return (
    <aside className="folder-rail" aria-label="Game folders">
      <header className="folder-rail__header">
        <div>
          <h2>Game folders</h2>
          <p>Group runs by experiment or harness pairing.</p>
        </div>
        <button
          className="icon-button folder-add-toggle"
          type="button"
          aria-label={adding ? "Cancel new folder" : "Create game folder"}
          aria-expanded={adding}
          onClick={() => setAdding((value) => !value)}
        >
          {adding ? <X size={17} aria-hidden="true" /> : <FolderPlus size={17} aria-hidden="true" />}
        </button>
      </header>

      {adding ? (
        <form className="folder-create" onSubmit={submit}>
          <label htmlFor="folder-name">Folder name</label>
          <div>
            <input
              id="folder-name"
              value={name}
              maxLength={60}
              placeholder="e.g. Baseline comparisons"
              autoFocus
              disabled={creating}
              onChange={(event) => setName(event.target.value)}
            />
            <button type="submit" disabled={creating || !name.trim()}>
              {creating ? "Saving…" : "Create"}
            </button>
          </div>
          {createError ? <p className="folder-create__error" role="alert">{createError}</p> : null}
        </form>
      ) : null}

      <nav className="folder-list" aria-label="Filter match records by folder">
        <button
          className={selectedId === "all" ? "folder-row folder-row--selected" : "folder-row"}
          type="button"
          aria-current={selectedId === "all" ? "page" : undefined}
          onClick={() => onSelect("all")}
        >
          <FolderOpen size={16} aria-hidden="true" />
          <span>All matches</span>
          <strong>{totalMatches}</strong>
        </button>
        <button
          className={selectedId === "unfiled" ? "folder-row folder-row--selected" : "folder-row"}
          type="button"
          aria-current={selectedId === "unfiled" ? "page" : undefined}
          onClick={() => onSelect("unfiled")}
        >
          <Folder size={16} aria-hidden="true" />
          <span>Unfiled</span>
          <strong>{unfiledCount}</strong>
        </button>
        {folders.map((folder) => (
          <button
            className={selectedId === folder.id ? "folder-row folder-row--selected" : "folder-row"}
            type="button"
            aria-current={selectedId === folder.id ? "page" : undefined}
            key={folder.id}
            onClick={() => onSelect(folder.id)}
          >
            <Folder size={16} aria-hidden="true" />
            <span>{folder.name}</span>
            <strong>{folder.matchCount}</strong>
          </button>
        ))}
      </nav>
    </aside>
  );
}
