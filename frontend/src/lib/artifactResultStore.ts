"use client";

export type HtmlArtifact = {
  filename: string;
  previewUrl: string;
};

type Device = "desktop" | "phone";

type State = {
  artifacts: HtmlArtifact[];
  tabs: string[];
  active: string | null;
  open: boolean;
  fullscreen: boolean;
  device: Device;
  source: boolean;
  reload: number;
};

const empty: State = {
  artifacts: [],
  tabs: [],
  active: null,
  open: false,
  fullscreen: false,
  device: "desktop",
  source: false,
  reload: 0,
};

let state: State = empty;
const listeners = new Set<() => void>();
const holders = new Map<string, number>();

function publish(next: State) {
  state = next;
  listeners.forEach((listener) => listener());
}

export function subscribeArtifactResult(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getArtifactResult() {
  return state;
}

export function registerArtifact(file: HtmlArtifact) {
  const count = (holders.get(file.filename) ?? 0) + 1;
  holders.set(file.filename, count);
  if (count === 1) {
    publish({
      ...state,
      artifacts: [...state.artifacts, file],
      tabs: [...state.tabs, file.filename],
      active: file.filename,
      open: true,
      source: false,
    });
  }
  return () => {
    const left = (holders.get(file.filename) ?? 1) - 1;
    if (left > 0) {
      holders.set(file.filename, left);
      return;
    }
    holders.delete(file.filename);
    const artifacts = state.artifacts.filter((item) => item.filename !== file.filename);
    const tabs = state.tabs.filter((id) => id !== file.filename);
    const active = state.active === file.filename ? tabs[tabs.length - 1] ?? null : state.active;
    publish({
      ...state,
      artifacts,
      tabs,
      active,
      open: Boolean(active) && state.open,
      fullscreen: Boolean(active) && state.fullscreen,
    });
  };
}

export function openArtifact(filename: string) {
  if (!state.artifacts.some((item) => item.filename === filename)) return;
  const tabs = state.tabs.includes(filename) ? state.tabs : [...state.tabs, filename];
  publish({ ...state, tabs, active: filename, open: true, source: false });
}

export function closeArtifactPanel() {
  publish({ ...state, open: false, fullscreen: false });
}

export function closeArtifactTab(filename: string) {
  const tabs = state.tabs.filter((id) => id !== filename);
  const active = state.active === filename ? tabs[tabs.length - 1] ?? null : state.active;
  publish({
    ...state,
    tabs,
    active,
    open: Boolean(active),
    fullscreen: Boolean(active) && state.fullscreen,
  });
}

export function setArtifactDevice(device: Device) {
  publish({ ...state, device });
}

export function toggleArtifactFullscreen() {
  publish({ ...state, fullscreen: !state.fullscreen, open: true });
}

export function toggleArtifactSource() {
  publish({ ...state, source: !state.source });
}

export function reloadArtifact() {
  publish({ ...state, reload: state.reload + 1, source: false });
}
