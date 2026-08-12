import { useEffect, useState } from 'react';

import { api, UnauthorizedError } from '../api';
import { accessToken, clearAccessToken, completeLogin, login, logout } from '../oidc';
import type { Identity } from '../types';
import { messageFor } from './messageFor';

export function useAuth() {
  const [token, setToken] = useState<string | null>(accessToken());
  const [identity, setIdentity] = useState<Identity>();
  const [authError, setAuthError] = useState<string>();

  useEffect(() => {
    completeLogin()
      .then(setToken)
      .catch((reason: unknown) => setAuthError(messageFor(reason)));
  }, []);

  useEffect(() => {
    if (!token) return;
    api
      .me(token)
      .then(setIdentity)
      .catch((reason: unknown) => {
        if (reason instanceof UnauthorizedError) {
          clearAccessToken();
          setToken(null);
          setIdentity(undefined);
          return;
        }
        setAuthError(messageFor(reason));
      });
  }, [token]);

  return {
    token,
    setToken,
    identity,
    authError,
    setAuthError,
    login,
    logout
  };
}
