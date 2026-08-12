import { describe, expect, it } from 'vitest';
import { authorizationHeader } from './api';

describe('authorizationHeader', () => {
  it('formats the access token as a bearer authorization header', () => {
    expect(authorizationHeader('test-access-token')).toEqual({
      Authorization: 'Bearer test-access-token'
    });
  });
});
