import { Component, Suspense, type ReactNode } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import type { Aircraft } from "./Research";

class SceneBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <p className="research-empty">
        3D is unavailable. The traffic table and 2D map remain available.
      </p>
    ) : (
      this.props.children
    );
  }
}

export default function ResearchScene({
  visible,
  selected,
  onSelect,
}: {
  visible: Aircraft[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <SceneBoundary>
      <Suspense fallback={<p>Loading 3D view…</p>}>
        <Canvas camera={{ position: [0, 65, 45], fov: 50 }}>
          <ambientLight intensity={1.8} />
          <directionalLight position={[10, 20, 10]} intensity={2} />
          <gridHelper args={[160, 16, "#46574c", "#293c33"]} />
          <OrbitControls makeDefault />
          {visible.map((a) => (
            <mesh
              key={a.id}
              position={[a.x_nm, (a.altitude_ft || 0) / 1500, -a.y_nm]}
              onClick={() => onSelect(a.id)}
            >
              <coneGeometry args={[a.id === selected ? 0.6 : 0.4, 1.2, 3]} />
              <meshStandardMaterial
                color={a.id === selected ? "#f8b65b" : "#d9e6da"}
              />
            </mesh>
          ))}
        </Canvas>
      </Suspense>
    </SceneBoundary>
  );
}
