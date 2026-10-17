import React from 'react'
import ReactDOM from 'react-dom/client'
import '@fontsource-variable/inter/wght.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/components.css'
import './styles/login.css'
import App from './App'
import { ThemeProvider } from './context/ThemeProvider'

// Prevent the mouse wheel from changing focused numeric inputs during data entry.
if (typeof document !== 'undefined') {
  document.addEventListener(
    'wheel',
    (event) => {
      const target = event.target
      if (target && target.tagName === 'INPUT' && target.type === 'number') {
        target.blur()
      }
    },
    true,
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </React.StrictMode>,
)
