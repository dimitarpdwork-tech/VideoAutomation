import {snapshot, isSameSiteGet} from '../../../lib/studio';
export const dynamic = 'force-dynamic';
export async function GET(request) {
  if (!isSameSiteGet(request)) return Response.json({error: 'Only dashboard requests are allowed.'}, {status: 403});
  try {
    return Response.json(await snapshot(new URL(request.url).searchParams.get('channel') || 'main'), {headers: {'Cache-Control': 'no-store'}});
  } catch (error) {
    return Response.json({error: error.message}, {status: 500});
  }
}
