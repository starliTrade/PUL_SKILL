/**
 * Clean, zero-side-effect browser-native fetch shim for cross-fetch.
 * Replaces cross-fetch/dist/browser-ponyfill.js which illegally attempts to mutate
 * read-only properties on window.fetch in strict mode / WebKit / Safari environments.
 */

const g: any = typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : global);

const nativeFetch = typeof g.fetch === 'function' ? g.fetch.bind(g) : (() => Promise.reject(new Error('Fetch not supported')));
const nativeHeaders = g.Headers || class {};
const nativeRequest = g.Request || class {};
const nativeResponse = g.Response || class {};

export default nativeFetch;
export { nativeFetch as fetch, nativeHeaders as Headers, nativeRequest as Request, nativeResponse as Response };


