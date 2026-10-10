# Optional GLB assets

The current village uses procedural geometry and works without downloaded assets. Place licensed models in this directory and load them with Drei `useGLTF('/models/name.glb')` inside `world/Village.tsx`'s entity renderer (or an extracted geometry component).

Keep the animated outer group, stable entity IDs, click handlers, and ground-plane x/z coordinates. Normalize model origin to the ground and scale it to roughly 2 × 2 world units for a building. Reuse cached geometry/materials, preload common assets, and preserve the procedural fallback. Record asset source and license beside each added model. Do not mix GLB animation time with authoritative tick time.
