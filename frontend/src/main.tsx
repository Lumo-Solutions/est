import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Self-hosted (docs/ui-design-system.md section 2.2) -- imported here, not
// via a CSS @import in index.css, because Vite's asset pipeline only
// rewrites/copies a package's font url() references when the CSS is
// pulled in from a JS entry point; a CSS-level @import of the same file
// left the .woff/.woff2 files unbundled (confirmed: `npm run build`
// warned every one "didn't resolve at build time" and none were copied to
// dist/), which would have silently fallen back to a system font in
// production -- exactly the kind of gap this phase's air-gapped
// constraint exists to prevent.
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-sans/700.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
