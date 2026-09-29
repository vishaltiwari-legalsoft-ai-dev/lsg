import { NextResponse, type NextRequest } from "next/server";

// The screens bind to 127.0.0.1:5000 and proxy /api to the engine. That keeps
// other machines out, but not a page elsewhere whose own hostname is
// re-pointed at 127.0.0.1 (DNS rebinding): its requests would arrive here
// same-origin, read contacts and start paid research. Only our two hosts
// are answered; anything else is refused before the proxy.
const ALLOWED_HOSTS = new Set(["127.0.0.1:5000", "localhost:5000"]);

export function proxy(request: NextRequest) {
  const host = request.headers.get("host") ?? "";
  if (!ALLOWED_HOSTS.has(host)) {
    return new NextResponse("Forbidden", { status: 403 });
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
