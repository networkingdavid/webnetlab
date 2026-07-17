import axios from 'axios';

// Use a relative base so requests always go to the same host that served the
// page.  In development Vite proxies /api → http://backend:8000 (see
// vite.config.ts).  In production the nginx reverse-proxy does the same.
export const api = axios.create({ baseURL: '' });
