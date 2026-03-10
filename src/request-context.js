function hasOwnHeader(headers, name) {
  return Object.prototype.hasOwnProperty.call(headers, name);
}

export function readHeader(headers, name) {
  const value = headers[name];
  if (Array.isArray(value)) return value[0] ?? null;
  return value ?? null;
}

export function readFirstHeader(headers, ...names) {
  for (const name of names) {
    const value = readHeader(headers, name);
    if (value !== null && value !== undefined && value !== '') {
      return value;
    }
  }
  return null;
}

export function mergeRequestContext(req, fallback = {}) {
  const authorizationHeaderPresent = hasOwnHeader(req.headers, 'authorization');
  const authorization = authorizationHeaderPresent
    ? readHeader(req.headers, 'authorization')
    : (fallback.authorization ?? null);

  const targetHeaderNames = [
    'x-zendesk-subdomain',
    'zendesk-subdomain',
    'x-zendesk-base-url',
    'zendesk-base-url',
  ];
  const hasAnyTargetHeader = targetHeaderNames.some(name => hasOwnHeader(req.headers, name));

  const zendeskSubdomainHeader = readFirstHeader(
    req.headers,
    'x-zendesk-subdomain',
    'zendesk-subdomain',
  );
  const zendeskBaseUrlHeader = readFirstHeader(
    req.headers,
    'x-zendesk-base-url',
    'zendesk-base-url',
  );

  return {
    authorization,
    // Target overrides are request-scoped so stale connector inputs do not bleed across a session.
    zendeskSubdomain: hasAnyTargetHeader ? zendeskSubdomainHeader : null,
    zendeskBaseUrl: hasAnyTargetHeader ? zendeskBaseUrlHeader : null,
  };
}
