import { sveltekit } from '@sveltejs/kit/vite';

/** @type {import('vite').UserConfig} */
const config = {
  plugins: [sveltekit()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/manifest.webmanifest': 'http://localhost:8000',
      '/icons': 'http://localhost:8000'
    }
  }
};

export default config;
