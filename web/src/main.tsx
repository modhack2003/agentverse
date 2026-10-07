import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'
import './remote.css'
import './themes.css'
import { ThemeProvider } from './Themes'

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><ThemeProvider><App /></ThemeProvider></React.StrictMode>)
