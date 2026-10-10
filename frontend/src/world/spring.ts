export type Spring = { value: number; velocity: number };

/** Slightly underdamped spring: things pop into place with a soft bounce. */
export function stepSpring(spring: Spring, target: number, dt: number) {
  const step = Math.min(dt, 1 / 30);
  spring.velocity +=
    (170 * (target - spring.value) - 15 * spring.velocity) * step;
  spring.value += spring.velocity * step;
}
