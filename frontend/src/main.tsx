import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.tsx'
import './styles/global.css'

const container = document.getElementById('root')
if (!container) throw new Error('#root is missing from index.html')

createRoot(container).render(
  <StrictMode>
    {/* StrictMode double-invokes effects in dev. That is a feature here: it
        surfaces effects that are not cleanup-safe. useApi survives it because
        every request is tied to an AbortController that the cleanup aborts. */}
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
