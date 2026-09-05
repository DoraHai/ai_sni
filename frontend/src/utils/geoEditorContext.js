// Invalidate continuations before they can assign responses or start a second API call.
export function createEditorContext(readContext) {
  const captured = readContext()
  const active = () => captured.every((value, index) => value === readContext()[index]) && !captured[3]
  return {
    active,
    async wait(promise) {
      const result = await promise
      if (!active()) throw new Error('Editor context changed')
      return result
    },
  }
}
