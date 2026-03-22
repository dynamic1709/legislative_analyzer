export default async function handler(req, res) {
  const backendBase = (process.env.BACKEND_URL || "").trim().replace(/\/$/, "");

  if (!backendBase) {
    res.statusCode = 500;
    res.setHeader("content-type", "application/json");
    res.end(
      JSON.stringify({
        detail:
          "BACKEND_URL is not set. Configure it in Vercel Environment Variables.",
      })
    );
    return;
  }

  const incomingUrl = new URL(req.url, `https://${req.headers.host}`);
  const upstreamPath = incomingUrl.pathname.replace(/^\/api(\/|$)/, "/");
  const upstreamUrl = `${backendBase}${upstreamPath}${incomingUrl.search}`;

  const headers = { ...req.headers };
  delete headers.host;

  const init = {
    method: req.method,
    headers,
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    // Node fetch requires duplex for streaming request bodies.
    init.body = req;
    init.duplex = "half";
  }

  let upstreamResponse;
  try {
    upstreamResponse = await fetch(upstreamUrl, init);
  } catch (error) {
    res.statusCode = 502;
    res.setHeader("content-type", "application/json");
    res.end(
      JSON.stringify({
        detail: "Failed to reach upstream backend.",
        error: error?.message || String(error),
      })
    );
    return;
  }

  res.statusCode = upstreamResponse.status;
  upstreamResponse.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (lower === "transfer-encoding") return;
    res.setHeader(key, value);
  });

  const body = Buffer.from(await upstreamResponse.arrayBuffer());
  res.end(body);
}
