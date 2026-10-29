import {Readable} from 'node:stream';
import {media, isSameSiteGet} from '../../../lib/studio';
export const dynamic = 'force-dynamic';
// Streams a finished video or thumbnail so it can be watched before approval.
export async function GET(request) {
  if (!isSameSiteGet(request)) return new Response('Forbidden', {status: 403});
  const query = new URL(request.url).searchParams;
  try {
    const result = await media(query.get('channel') || 'main', query.get('batch'), query.get('file'), request.headers.get('range'));
    return new Response(result.stream ? Readable.toWeb(result.stream) : null,
      {status: result.status, headers: {...result.headers, 'Cache-Control': 'no-store'}});
  } catch (error) {
    return new Response(error.code === 'ENOENT' ? 'Not found' : 'Invalid request', {status: error.code === 'ENOENT' ? 404 : 400});
  }
}
