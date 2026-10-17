import React from 'react';
import ReactDOM from 'react-dom/client';
import '@fontsource/ibm-plex-sans-condensed/latin-400.css';
import '@fontsource/ibm-plex-sans-condensed/latin-500.css';
import '@fontsource/ibm-plex-sans-condensed/latin-600.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@fontsource/ibm-plex-mono/latin-500.css';
import App from './App';
import './style.css';
class AppBoundary extends React.Component<{children:React.ReactNode},{failed:boolean}>{state={failed:false};static getDerivedStateFromError(){return {failed:true}}render(){return this.state.failed?<main className="startup" role="alert"><div className="wordmark">uita<span>.</span></div><h1>The interface needs to reload</h1><p>The simulation state is held by the backend. Reload this interface to reconnect and continue.</p><button className="primary" onClick={()=>window.location.reload()}>Reload interface</button></main>:this.props.children}}
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><AppBoundary><App/></AppBoundary></React.StrictMode>);
