import { FlipHorizontal2, Pause, Play, SkipBack, SkipForward, StepBack, StepForward } from "lucide-react";

interface ReplayControlsProps {
  ply: number;
  maxPly: number;
  playing: boolean;
  onChange(ply: number): void;
  onTogglePlaying(): void;
  onFlip(): void;
}

export function ReplayControls({ ply, maxPly, playing, onChange, onTogglePlaying, onFlip }: ReplayControlsProps) {
  return (
    <div className="replay-controls" aria-label="Replay controls">
      <div className="transport-controls">
        <button className="icon-button" type="button" onClick={() => onChange(0)} disabled={ply === 0} aria-label="First position">
          <SkipBack size={17} aria-hidden="true" />
        </button>
        <button className="icon-button" type="button" onClick={() => onChange(ply - 1)} disabled={ply === 0} aria-label="Previous move">
          <StepBack size={17} aria-hidden="true" />
        </button>
        <button className="icon-button icon-button--transport" type="button" onClick={onTogglePlaying} disabled={maxPly === 0} aria-label={playing ? "Pause replay" : "Play replay"}>
          {playing ? <Pause size={18} aria-hidden="true" /> : <Play size={18} aria-hidden="true" />}
        </button>
        <button className="icon-button" type="button" onClick={() => onChange(ply + 1)} disabled={ply === maxPly} aria-label="Next move">
          <StepForward size={17} aria-hidden="true" />
        </button>
        <button className="icon-button" type="button" onClick={() => onChange(maxPly)} disabled={ply === maxPly} aria-label="Last position">
          <SkipForward size={17} aria-hidden="true" />
        </button>
      </div>
      <label className="replay-range">
        <span>Replay cursor</span>
        <input
          type="range"
          min="0"
          max={maxPly}
          value={ply}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        <output>{ply}/{maxPly}</output>
      </label>
      <button className="icon-button" type="button" onClick={onFlip} aria-label="Flip board">
        <FlipHorizontal2 size={18} aria-hidden="true" />
      </button>
    </div>
  );
}

