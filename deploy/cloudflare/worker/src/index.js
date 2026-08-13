export default {
  async fetch(request, env) {
    const originUrl = new URL(request.url);
    originUrl.protocol = "http:";
    originUrl.hostname = "koebinar.internal";
    originUrl.port = "";

    return env.KOEBINAR_ORIGIN.fetch(new Request(originUrl, request));
  },
};
