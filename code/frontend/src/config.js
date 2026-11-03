// Where the backend lives. Set VITE_API_BASE (in .env.local or in Vercel's
// environment variables) to change it without editing code.
export const BASE =
  import.meta.env.VITE_API_BASE || "https://norm-mem-temperature-few.trycloudflare.com";

// The API key is kept for this browser tab only (sessionStorage), never in code.
const KEY_NAME = "testkit_api_key";

export function getApiKey() {
  try {
    return sessionStorage.getItem(KEY_NAME) || "";
  } catch {
    return "";
  }
}

export function setApiKey(value) {
  try {
    sessionStorage.setItem(KEY_NAME, value);
  } catch {
    /* storage unavailable: the key then lasts only until the page reloads */
  }
}

// Adds the X-API-Key header to every request sent to our backend, so the old
// Load Tester tab and the Test Platform tab both work when the server needs a key.
if (typeof window !== "undefined" && !window.__apiKeyFetchPatched) {
  const original = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const key = getApiKey();
    if (key && String(input).startsWith(BASE)) {
      init = { ...init, headers: { ...(init.headers || {}), "X-API-Key": key } };
    }
    return original(input, init);
  };
  window.__apiKeyFetchPatched = true;
}