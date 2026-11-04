import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import Shell from './Shell.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <Shell />
    </ErrorBoundary>
  </StrictMode>,
)