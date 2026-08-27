import { copyFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const unitRoot = resolve(import.meta.dirname, '..')

// Keep the established dashboard.html URL as a second entry for the
// standalone Vue app. Both entries redirect to the current GEO overview.
await copyFile(
  resolve(unitRoot, 'dist/index.html'),
  resolve(unitRoot, 'dist/dashboard.html'),
)
