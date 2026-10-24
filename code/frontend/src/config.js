// Where the backend lives. Set VITE_API_BASE (in .env.local or in Vercel's
// environment variables) to change it without editing code.
export const BASE =
  import.meta.env.VITE_API_BASE || "https://norm-mem-temperature-few.trycloudflare.com";