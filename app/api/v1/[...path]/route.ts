/** Development-only bridge. Production local build is served directly by FastAPI. */
async function proxy(request: Request) {
  const source = new URL(request.url);
  const target = new URL(source.pathname + source.search, 'http://127.0.0.1:8000');
  const headers = new Headers(request.headers);
  headers.delete('host');
  // Backend still validates the browser's original Origin and session.
  const response = await fetch(target, {
    method: request.method,
    headers,
    body: ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer(),
    redirect: 'manual',
  });
  return new Response(response.body, {status:response.status,headers:response.headers});
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
