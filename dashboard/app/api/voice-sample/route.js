import {Readable} from 'node:stream';
import {voiceSample, isSameSiteGet} from '../../../lib/studio';
export const dynamic = 'force-dynamic';
// Streams a narrator sample (Settings > Voice) so voices can be compared by ear.
export async function GET(request) {
  if (!isSameSiteGet(request)) return new Response('Forbidden', {status: 403});
  try {
    const result = await voiceSample(new URL(request.url).searchParams.get('file'), request.headers.get('range'));
    return new Response(result.stream ? Readable.toWeb(result.stream) : null,
      {status: result.status, headers: {...result.headers, 'Cache-Control': 'no-store'}});
  } catch (error) {
    return new Response(error.code === 'ENOENT' ? 'Not found' : 'Invalid request', {status: error.code === 'ENOENT' ? 404 : 400});
  }
}
