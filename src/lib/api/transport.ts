import { ApiError, EngineUnreachableError, isApiErrorBody } from "./errors";

export type QueryValue = string | number | boolean | null | undefined;

export interface RequestSpec {
  method: "GET" | "POST" | "PUT" | "PATCH";
  path: string;
  query?: Record<string, QueryValue>;
  body?: unknown;
  /** A file upload. Sent as multipart; the browser sets the boundary header. */
  form?: FormData;
  signal?: AbortSignal;
}

/**
 * How a request reaches an answer: over HTTP to the engine, or from the
 * in-memory fixture server. Endpoint functions never know which.
 */
export interface Transport {
  json<T>(spec: RequestSpec): Promise<T>;
  text(spec: RequestSpec): Promise<string>;
}

export function buildSearch(query: RequestSpec["query"]): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const search = params.toString();
  return search ? `?${search}` : "";
}

export function httpTransport(base: string, fetchImpl: typeof fetch = fetch): Transport {
  async function send(spec: RequestSpec, accept: string): Promise<Response> {
    const url = `${base}${spec.path}${buildSearch(spec.query)}`;
    const headers: Record<string, string> = { Accept: accept };
    let body: BodyInit | undefined;
    if (spec.form) {
      body = spec.form;
    } else if (spec.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(spec.body);
    }
    let response: Response;
    try {
      response = await fetchImpl(url, { method: spec.method, headers, body, signal: spec.signal });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
      throw new EngineUnreachableError(cause);
    }

    if (!response.ok) {
      let body: unknown = null;
      try {
        body = await response.json();
      } catch {
        // Not the contract's envelope — fall through to a plain status error.
      }
      if (isApiErrorBody(body)) {
        throw new ApiError(
          response.status,
          body.error.code,
          body.error.message,
          body.error.fix ?? null,
        );
      }
      throw new ApiError(
        response.status,
        "http_error",
        `The engine answered ${response.status} for ${spec.path}.`,
        null,
      );
    }
    return response;
  }

  return {
    async json<T>(spec: RequestSpec): Promise<T> {
      const response = await send(spec, "application/json");
      if (response.status === 204) return undefined as T;
      return (await response.json()) as T;
    },
    async text(spec: RequestSpec): Promise<string> {
      const response = await send(spec, "text/csv, text/plain");
      return response.text();
    },
  };
}
