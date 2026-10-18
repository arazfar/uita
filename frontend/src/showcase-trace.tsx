import { createRoot } from "react-dom/client";
import {
  SimulationTrace,
  type SimulationTraceProps,
} from "./components/SimulationTrace";
import "./showcase-trace.css";
let root: ReturnType<typeof createRoot> | undefined;
export function renderAgentTrace(
  props: SimulationTraceProps & { sourceKey: string; hidden: boolean },
) {
  const container = document.getElementById("agent-trace");
  if (!container) return;
  container.hidden = props.hidden;
  root ??= createRoot(container);
  root.render(
    props.hidden ? null : <SimulationTrace key={props.sourceKey} {...props} />,
  );
}
