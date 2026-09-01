export async function runSeoBatch(items, worker, { concurrency = 1, limit = 50 } = {}) {
  const accepted = items.slice(0, limit)
  const result = {
    completed: [],
    failed: [],
    skipped: items.slice(limit),
  }
  let cursor = 0

  async function consume() {
    while (cursor < accepted.length) {
      const index = cursor
      cursor += 1
      const item = accepted[index]
      try {
        result.completed.push({ item, value: await worker(item) })
      } catch (error) {
        result.failed.push({ item, error })
      }
    }
  }

  await Promise.all(Array.from(
    { length: Math.min(Math.max(1, concurrency), accepted.length) },
    () => consume(),
  ))
  return result
}
