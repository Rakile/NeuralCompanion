export type AuthorizedMediaClient = {
  identityKey: string;
  authorizedMediaUrl: (
    path: string,
    params?: Record<string, unknown>,
  ) => Promise<{ url: string; expiresAt: number }>;
};

export type ResolvedAuthorizedMedia = { url: string; expiresAt: number };

function paramsKey(params: Record<string, unknown>): string {
  return JSON.stringify(
    Object.entries(params)
      .filter(([, value]) => value !== undefined && value !== null && String(value) !== '')
      .sort(([left], [right]) => left.localeCompare(right)),
  );
}

export class AuthorizedMediaResolver {
  private readonly cache = new Map<string, ResolvedAuthorizedMedia>();
  private readonly client: AuthorizedMediaClient;
  private readonly clock: () => number;

  constructor(
    client: AuthorizedMediaClient,
    clock: () => number = Date.now,
  ) {
    this.client = client;
    this.clock = clock;
  }

  async resolve(path: string, params: Record<string, unknown> = {}): Promise<ResolvedAuthorizedMedia> {
    const key = `${this.client.identityKey}|${path}|${paramsKey(params)}`;
    const cached = this.cache.get(key);
    const now = this.clock();
    if (cached && (!cached.expiresAt || now < cached.expiresAt - 30_000)) {
      return cached;
    }
    const resolved = await this.client.authorizedMediaUrl(path, params);
    this.cache.set(key, resolved);
    return resolved;
  }

  clear(): void {
    this.cache.clear();
  }
}

export function authorizedMediaParamsKey(params: Record<string, unknown>): string {
  return paramsKey(params);
}
