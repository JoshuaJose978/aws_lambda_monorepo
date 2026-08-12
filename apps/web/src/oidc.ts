type ProviderMetadata = {
  authorization_endpoint: string;
  token_endpoint: string;
  end_session_endpoint?: string;
};

const issuer = import.meta.env.VITE_OIDC_ISSUER.replace(/\/$/, '');
const clientId = import.meta.env.VITE_OIDC_CLIENT_ID;
const redirectUri = window.location.origin;
const verifierKey = 'oidc_pkce_verifier';
const stateKey = 'oidc_state';
const tokenKey = 'oidc_access_token';
const exchangingKey = 'oidc_exchanging_code';

function required(value: string, name: string): string {
  if (!value) throw new Error(`${name} is not configured`);
  return value;
}

async function metadata(): Promise<ProviderMetadata> {
  const response = await fetch(
    `${required(issuer, 'VITE_OIDC_ISSUER')}/.well-known/openid-configuration`
  );
  if (!response.ok) throw new Error('Unable to load OIDC configuration');
  return response.json() as Promise<ProviderMetadata>;
}

let providerPromise: Promise<ProviderMetadata> | null = null;

async function getProvider(): Promise<ProviderMetadata> {
  if (!providerPromise) {
    providerPromise = metadata().catch((error) => {
      // Allow a retry if the discovery request failed.
      providerPromise = null;
      throw error;
    });
  }
  return providerPromise;
}

function randomString(): string {
  const values = crypto.getRandomValues(new Uint8Array(32));
  return Array.from(values, (value) => value.toString(16).padStart(2, '0')).join('');
}

async function challenge(verifier: string): Promise<string> {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return btoa(String.fromCharCode(...new Uint8Array(hash)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');
}

export function accessToken(): string | null {
  return sessionStorage.getItem(tokenKey);
}

export function clearAccessToken(): void {
  sessionStorage.removeItem(tokenKey);
}

export async function login(): Promise<void> {
  const verifier = randomString();
  const state = randomString();
  sessionStorage.setItem(verifierKey, verifier);
  sessionStorage.setItem(stateKey, state);
  const provider = await getProvider();
  const url = new URL(provider.authorization_endpoint);
  url.search = new URLSearchParams({
    response_type: 'code',
    client_id: required(clientId, 'VITE_OIDC_CLIENT_ID'),
    redirect_uri: redirectUri,
    scope: 'openid email profile',
    state,
    code_challenge: await challenge(verifier),
    code_challenge_method: 'S256'
  }).toString();
  window.location.assign(url.toString());
}

export async function completeLogin(): Promise<string | null> {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  if (!code) return accessToken();
  // React StrictMode runs effects twice in dev; make the code exchange idempotent.
  if (sessionStorage.getItem(exchangingKey) === code) return accessToken();
  if (params.get('state') !== sessionStorage.getItem(stateKey))
    throw new Error('Invalid login state');
  const verifier = sessionStorage.getItem(verifierKey);
  if (!verifier) throw new Error('Missing PKCE verifier');

  // Clear the URL before we attempt token exchange so a second invocation
  // does not see the one-time authorization code.
  window.history.replaceState({}, document.title, redirectUri);
  sessionStorage.setItem(exchangingKey, code);

  const provider = await getProvider();
  const response = await fetch(provider.token_endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: required(clientId, 'VITE_OIDC_CLIENT_ID'),
      code,
      redirect_uri: redirectUri,
      code_verifier: verifier
    })
  });
  if (!response.ok) throw new Error('Unable to exchange login code');
  const tokens = (await response.json()) as { access_token: string };
  sessionStorage.setItem(tokenKey, tokens.access_token);
  sessionStorage.removeItem(verifierKey);
  sessionStorage.removeItem(stateKey);
  sessionStorage.removeItem(exchangingKey);
  return tokens.access_token;
}

export async function logout(): Promise<void> {
  clearAccessToken();
  const provider = await getProvider();
  const url = new URL(
    provider.end_session_endpoint ?? new URL('/logout', provider.authorization_endpoint).toString()
  );
  url.search = new URLSearchParams({
    client_id: required(clientId, 'VITE_OIDC_CLIENT_ID'),
    post_logout_redirect_uri: redirectUri
  }).toString();
  window.location.assign(url.toString());
}
