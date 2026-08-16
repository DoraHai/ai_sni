import { copyFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const unitRoot = resolve(import.meta.dirname, '..')

// Production currently redirects /deal-sniper/geo/ to dashboard.html.
// Keep that established URL as a second entry for the standalone Vue app.
await copyFile(
  resolve(unitRoot, 'dist/index.html'),
  resolve(unitRoot, 'dist/dashboard.html'),
)
