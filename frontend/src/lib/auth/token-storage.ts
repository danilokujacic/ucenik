/**
 * Plain (non-React) token storage. Lives outside the component tree so the
 * fetch client (lib/api/client.ts) can read/attach/clear tokens without a
 * circular import on AuthContext. AuthContext subscribes to `onLogout` to
 * react (redirect, clear user state) when the client forces a logout after
 * a failed refresh - see lib/api/client.ts's 401 handling.
 */

const ACCESS_KEY = "ucenik.access_token";
const REFRESH_KEY = "ucenik.refresh_token";

type Listener = () => void;
const logoutListeners = new Set<Listener>();

function isBrowser() {
  return typeof window !== "undefined";
}

export const tokenStorage = {
  getAccessToken(): string | null {
    if (!isBrowser()) return null;
    return window.localStorage.getItem(ACCESS_KEY);
  },

  getRefreshToken(): string | null {
    if (!isBrowser()) return null;
    return window.localStorage.getItem(REFRESH_KEY);
  },

  setTokens(accessToken: string, refreshToken?: string): void {
    if (!isBrowser()) return;
    window.localStorage.setItem(ACCESS_KEY, accessToken);
    if (refreshToken) {
      window.localStorage.setItem(REFRESH_KEY, refreshToken);
    }
  },

  clear(): void {
    if (!isBrowser()) return;
    window.localStorage.removeItem(ACCESS_KEY);
    window.localStorage.removeItem(REFRESH_KEY);
  },

  /** Called by the fetch client when a refresh attempt itself fails - the
   * only reliable "session is really over" signal (spec §3.1/§3.7). */
  onLogout(listener: Listener): () => void {
    logoutListeners.add(listener);
    return () => logoutListeners.delete(listener);
  },

  forceLogout(): void {
    this.clear();
    logoutListeners.forEach((l) => l());
  },
};
