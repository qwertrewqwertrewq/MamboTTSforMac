import html from "./index.html";

const R2_BASE = "https://r2.rinku.dpdns.org";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const pathname = url.pathname;

    // 1. 首页与文档页面
    if (pathname === "/" || pathname === "/index.html") {
      return new Response(html, {
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Cache-Control": "public, max-age=3600, s-maxage=86400",
        },
      });
    }

    // 2. 源码压缩包与大文件直链代理 / 302 重定向
    if (
      pathname === "/MamboTTSforMac-source.zip" ||
      pathname.endsWith(".zip") ||
      pathname.endsWith(".tar.gz") ||
      pathname.includes(".part") ||
      pathname === "/manifest.json"
    ) {
      return Response.redirect(`${R2_BASE}${pathname}`, 302);
    }

    // 3. 其他未知路径回退至首页或 404
    return new Response(html, {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
      },
      status: 200,
    });
  },
};
