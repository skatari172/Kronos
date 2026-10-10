/** Gold ring on the ground under the selected building or villager. */
export function Selection({ radius }: { radius: number }) {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.04, 0]}>
      <ringGeometry args={[radius, radius + 0.07, 48]} />
      <meshBasicMaterial color="#f3c776" transparent opacity={0.95} />
    </mesh>
  );
}
