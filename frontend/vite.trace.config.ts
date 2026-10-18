import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: '../showcase/candidates/trace-assets', emptyOutDir: true,
    lib: { entry: 'src/showcase-trace.tsx', formats: ['es'], fileName: () => 'agent-trace.js', cssFileName: 'agent-trace' },
  },
});
