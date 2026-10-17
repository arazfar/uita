import { createRoot } from 'react-dom/client'
import '@fontsource/ibm-plex-sans-condensed/latin-400.css'
import '@fontsource/ibm-plex-sans-condensed/latin-500.css'
import '@fontsource/ibm-plex-sans-condensed/latin-600.css'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-500.css'
import 'maplibre-gl/dist/maplibre-gl.css'
import './styles.css'
import App from './App'

createRoot(document.getElementById('root')!).render(<App />)
