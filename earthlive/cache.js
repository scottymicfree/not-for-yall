const cache = new Map();
export function getCache(key, ttlMs) {
  const item = cache.get(key);
  if (!item) return null;
  if (Date.now() - item.time > ttlMs) return null;
  return item.data;
}
export function setCache(key, data) {
  cache.set(key, { data, time: Date.now() });
}
