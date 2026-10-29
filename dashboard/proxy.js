// Every request must be addressed to this computer by name. A web page that
// re-points its own domain at 127.0.0.1 (DNS rebinding) sends its own host name
// and is refused here before any route runs.
import {NextResponse} from 'next/server';

const ALLOWED = new Set(['localhost', '127.0.0.1', '[::1]']);

export function proxy(request) {
  const host = (request.headers.get('host') || '').toLowerCase();
  const name = host.startsWith('[') ? host.slice(0, host.indexOf(']') + 1) : host.split(':')[0];
  if (!ALLOWED.has(name)) return new NextResponse('This dashboard only answers on localhost.', {status: 403});
  return NextResponse.next();
}

export const config = {matcher: '/:path*'};
