"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { Environment, Float, Lightformer } from "@react-three/drei";
import { EffectComposer, Noise, Vignette } from "@react-three/postprocessing";
import { useMemo, useRef } from "react";
import * as THREE from "three";

/** Scroll progress 0→1 written by the page (GSAP ScrollTrigger); read every frame, never re-renders. */
export type Progress = { current: number };

function Chrome({ rough = 0.16 }: { rough?: number }) {
  return <meshPhysicalMaterial color="#d9dde0" metalness={1} roughness={rough} clearcoat={1} clearcoatRoughness={0.2} envMapIntensity={1.15} />;
}

/** A segmented "tech ring": torus band plus ticked inner rail, like a dial on a ledger instrument. */
function TechRing({ radius, tube, ticks, tilt }: { radius: number; tube: number; ticks: number; tilt: [number, number, number] }) {
  const tickGeo = useMemo(() => new THREE.BoxGeometry(tube * 0.9, tube * 3.2, tube * 0.9), [tube]);
  const angles = useMemo(() => Array.from({ length: ticks }, (_, i) => (i / ticks) * Math.PI * 2), [ticks]);
  return (
    <group rotation={tilt}>
      <mesh>
        <torusGeometry args={[radius, tube, 48, 220]} />
        <Chrome />
      </mesh>
      <mesh>
        <torusGeometry args={[radius - tube * 3.4, tube * 0.28, 16, 200]} />
        <Chrome rough={0.32} />
      </mesh>
      {angles.map((a) => (
        <mesh key={a} geometry={tickGeo} position={[Math.cos(a) * (radius - tube * 1.9), Math.sin(a) * (radius - tube * 1.9), 0]}
          rotation={[0, 0, a + Math.PI / 2]}>
          <Chrome rough={0.25} />
        </mesh>
      ))}
    </group>
  );
}

/** Faceted dark stone: a low-poly icosahedron with jittered vertices, flat-shaded. */
function LedgerStone() {
  const geo = useMemo(() => {
    const g = new THREE.IcosahedronGeometry(0.92, 1);
    const p = g.attributes.position as THREE.BufferAttribute;
    const seen = new Map<string, number>();
    for (let i = 0; i < p.count; i++) {
      const key = `${p.getX(i).toFixed(3)},${p.getY(i).toFixed(3)},${p.getZ(i).toFixed(3)}`;
      let s = seen.get(key);
      if (s === undefined) {
        s = 0.86 + ((Math.sin(i * 12.9898) * 43758.5453) % 1 + 1) % 1 * 0.26;
        seen.set(key, s);
      }
      p.setXYZ(i, p.getX(i) * s, p.getY(i) * s * 1.08, p.getZ(i) * s);
    }
    g.computeVertexNormals();
    return g;
  }, []);
  return (
    <mesh geometry={geo}>
      <meshPhysicalMaterial color="#121314" metalness={0.55} roughness={0.38} flatShading clearcoat={0.6} envMapIntensity={1.4} />
    </mesh>
  );
}

function Rig({ progress, still, compact }: { progress?: Progress; still: boolean; compact: boolean }) {
  const root = useRef<THREE.Group>(null);
  const a = useRef<THREE.Group>(null);
  const b = useRef<THREE.Group>(null);
  const c = useRef<THREE.Group>(null);
  useFrame((state, dt) => {
    const p = progress?.current ?? 0;
    const t = still ? 0 : state.clock.elapsedTime;
    const pointer = still ? { x: 0, y: 0 } : state.pointer;
    if (a.current) a.current.rotation.set(0.35 + p * 1.6 + t * 0.06, t * 0.12 + p * 2.2, 0);
    if (b.current) b.current.rotation.set(-0.6 - p * 1.1, 0.4 + t * -0.09, t * 0.05 + p * 1.4);
    if (c.current) c.current.rotation.set(1.2 + t * 0.04 + p * 0.8, -0.2 - p * 1.8, t * -0.07);
    if (root.current) {
      const g = root.current;
      g.rotation.y = THREE.MathUtils.damp(g.rotation.y, pointer.x * 0.25, 3, dt);
      g.rotation.x = THREE.MathUtils.damp(g.rotation.x, -pointer.y * 0.15, 3, dt);
      g.position.y = compact ? 0 : -p * 1.2;
      const s = compact ? 1 : 1 + p * 0.35;
      g.scale.setScalar(s);
    }
    if (!compact) state.camera.position.z = THREE.MathUtils.damp(state.camera.position.z, 7.2 - p * 1.6, 4, dt);
  });
  return (
    <group ref={root}>
      <Float speed={still ? 0 : 1.1} rotationIntensity={0.15} floatIntensity={0.35}>
        <LedgerStone />
        <group ref={a}><TechRing radius={2.05} tube={0.055} ticks={48} tilt={[0, 0, 0]} /></group>
        <group ref={b}><TechRing radius={2.6} tube={0.04} ticks={0} tilt={[0.2, 0, 0]} /></group>
        <group ref={c}><TechRing radius={1.5} tube={0.035} ticks={24} tilt={[0, 0.3, 0]} /></group>
      </Float>
    </group>
  );
}

export default function LedgerScene({ progress, still = false, compact = false, effects = true }: {
  progress?: Progress; still?: boolean; compact?: boolean; effects?: boolean;
}) {
  return (
    <Canvas
      dpr={[1, 1.75]}
      camera={{ position: [0, 0, compact ? 7.6 : 7.2], fov: 35 }}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      frameloop={still ? "demand" : "always"}
      fallback={<div className="size-full bg-[radial-gradient(closest-side,rgb(191_213_221/0.14),transparent)]" />}
      aria-hidden
    >
      <Environment resolution={256} frames={1}>
        <Lightformer form="rect" intensity={4} position={[0, 5, -2]} scale={[10, 1.2, 1]} rotation-x={Math.PI / 2} />
        <Lightformer form="rect" intensity={2.5} position={[-5, 1, 0]} scale={[3, 8, 1]} rotation-y={Math.PI / 2} />
        <Lightformer form="rect" intensity={1.6} color="#bfd5dd" position={[5, -1, 0]} scale={[3, 8, 1]} rotation-y={-Math.PI / 2} />
        <Lightformer form="ring" intensity={2} position={[0, 0, 6]} scale={3} />
      </Environment>
      <Rig progress={progress} still={still} compact={compact} />
      {effects && (
        <EffectComposer multisampling={0}>
          <Noise opacity={0.045} premultiply />
          <Vignette eskil={false} offset={0.2} darkness={0.85} />
        </EffectComposer>
      )}
    </Canvas>
  );
}
