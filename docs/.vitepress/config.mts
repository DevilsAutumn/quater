import { Buffer } from "node:buffer";
import { defineConfig } from "vitepress";
import type { DefaultTheme, HeadConfig } from "vitepress";

type DocsVersion = {
  label: string;
  base: string;
  index: string;
};

const language = "en";
const sourceDirectory = "dev";
const docsChannel =
  process.env.QUATER_DOCS_CHANNEL === "stable" ? "stable" : "dev";
const publishedDirectory = docsChannel;
// Only the stable channel is indexed. Dev mirrors unreleased changes, so it is
// kept out of search results to avoid duplicate content competing with stable.
const robotsContent = docsChannel === "stable" ? "index,follow" : "noindex,follow";
const siteUrl = "https://quater.devilsautumn.com";
const socialImageUrl = `${siteUrl}/logo-white-bg.svg`;
const defaultDescription =
  "Quater is a typed Python backend framework building applications where AI agents are first-class citizens.";
const structuredData = {
  "@context": "https://schema.org",
  "@type": "SoftwareSourceCode",
  name: "Quater",
  description: defaultDescription,
  url: siteUrl,
  codeRepository: "https://github.com/DevilsAutumn/quater",
  programmingLanguage: "Python",
  runtimePlatform: "Python 3.11+",
  license: "https://opensource.org/licenses/MIT",
};
const sourcePrefix = `/${language}/${sourceDirectory}`;
const publishedPrefix = `/${language}/${publishedDirectory}`;
const currentDocs: DocsVersion = {
  label: publishedDirectory === "stable" ? "Stable" : "Dev",
  base: `${publishedPrefix}/`,
  index: `${publishedPrefix}/index`,
};

function sidebarFor(version: DocsVersion): DefaultTheme.SidebarItem[] {
  return [
    {
      text: "Start Here",
      items: [
        { text: "Overview", link: version.index },
        { text: "Quickstart", link: `${version.base}quickstart` },
        { text: "Why Quater Exists", link: `${version.base}why-quater` },
      ],
    },
    {
      text: "Core Concepts",
      items: [
        { text: "Routes and Handlers", link: `${version.base}routes-handlers` },
        {
          text: "HTTP, MCP, and CLI Surfaces",
          link: `${version.base}surfaces`,
        },
        { text: "Auth Model", link: `${version.base}auth-model` },
        { text: "Resources and State", link: `${version.base}resources` },
        {
          text: "Middleware and Errors",
          link: `${version.base}middleware-errors`,
        },
      ],
    },
    {
      text: "Guides",
      items: [
        { text: "MCP Tools", link: `${version.base}mcp` },
        { text: "Actions and CLI", link: `${version.base}actions` },
        { text: "Testing", link: `${version.base}testing` },
        { text: "Deployment", link: `${version.base}deployment` },
        { text: "Security", link: `${version.base}security` },
      ],
    },
    {
      text: "Reference",
      collapsed: true,
      items: [
        { text: "Overview", link: `${version.base}reference/` },
        { text: "Application", link: `${version.base}reference/application` },
        { text: "Request", link: `${version.base}reference/request` },
        { text: "Parameters", link: `${version.base}reference/parameters` },
        { text: "Responses", link: `${version.base}reference/responses` },
        { text: "Resources", link: `${version.base}reference/resources` },
        { text: "Auth and Security", link: `${version.base}reference/auth` },
        {
          text: "Observability",
          link: `${version.base}reference/observability`,
        },
        { text: "Testing", link: `${version.base}reference/testing` },
      ],
    },
    {
      text: "Project",
      items: [
        { text: "Contributing", link: `${version.base}contributing` },
        { text: "Stability", link: `${version.base}stability` },
        { text: "Changelog / Release Notes", link: `${version.base}changelog` },
        { text: "Known Limitations", link: `${version.base}known-limitations` },
      ],
    },
  ];
}

const versionSidebars = Object.fromEntries(
  [[currentDocs.base, sidebarFor(currentDocs)]],
) as DefaultTheme.SidebarMulti;

// In the stable build, transformHtml rewrites "/en/dev/" navigation links to
// "/en/stable/". The version switcher must still point at the dev channel, so it
// uses a sentinel the rewrite ignores and restores afterwards.
const devIndexLink = `/${language}/dev/index`;
const devChannelSentinel = "/__quater-dev-channel__/index";
const versionItems = [
  { text: "Stable", link: `/${language}/stable/index` },
  { text: "Dev", link: docsChannel === "stable" ? devChannelSentinel : devIndexLink },
];

const currentBase = currentDocs.base;
const rewrites =
  publishedDirectory === sourceDirectory
    ? undefined
    : (id: string) =>
        id.startsWith(`${language}/${sourceDirectory}/`)
          ? id.replace(
              `${language}/${sourceDirectory}/`,
              `${language}/${publishedDirectory}/`,
            )
          : id;

const nav: DefaultTheme.NavItem[] = [
  { text: "Guide", link: `${currentBase}quickstart` },
  { text: "Concepts", link: `${currentBase}surfaces` },
  { text: "CLI", link: `${currentBase}actions` },
  { text: "MCP", link: `${currentBase}mcp` },
  {
    text: "Version",
    items: versionItems,
  },
];

const pypiIcon = {
  svg: `<svg role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" id="Pypi--Streamline-Simple-Icons" height="24" width="24"><title>PyPI</title><path d="M23.922 13.58v3.912L20.55 18.72l-0.078 0.055 0.052 0.037 3.45 -1.256 0.026 -0.036v-3.997l-0.053 -0.036 -0.025 0.092zm-0.301 -7.962 -3.04 1.107v3.912l3.339 -1.215V5.509zm0.299 7.839V9.544l-3.336 1.215v3.913zm-3.45 1.253V10.8l-3.3 1.2v3.913zm-3.436 5.286v-3.912l-3.313 1.206v3.912zm0.136 -3.939v3.868l3.314 -1.206V14.85l-3.314 1.206zm2.093 1.882c-0.367 0.134 -0.663 -0.074 -0.663 -0.463s0.296 -0.814 0.663 -0.947c0.365 -0.133 0.662 0.075 0.662 0.464s-0.297 0.814 -0.662 0.946zm-6.038 -8.624 0.365 -0.132 -3.285 -1.197 -3.323 1.21 0.102 0.037 3.184 1.16zm7.282 1.349V6.751L17.17 7.965v3.913zm-3.449 1.254V8.005l-3.302 1.202v3.912zm-3.415 -2.672 -3.336 1.215v3.913l3.336 -1.215zm-6.736 3.919 3.322 1.209v-3.913L6.907 9.252zm3.433 -5.292 3.281 1.193V5.198l-3.28 -1.193zm10.167 -5.158L17.19 3.922v3.913l3.317 -1.207zM16.95 3.903 13.724 2.73l-3.269 1.19 3.225 1.174zm-1.585 0.703 -1.624 0.592v3.868l3.317 -1.207V3.991l-1.693 0.615zm-0.391 2.778c-0.367 0.134 -0.662 -0.074 -0.662 -0.464s0.295 -0.813 0.662 -0.946c0.366 -0.133 0.663 0.074 0.663 0.464s-0.297 0.813 -0.663 0.946zM10.229 18.41v-3.914l-3.322 -1.209V17.2zm3.449 -1.228v-3.913l-3.371 1.227v3.913zm0.078 -0.028 3.3 -1.2V12.04l-3.3 1.2zm-0.078 4.063 -3.371 1.227v-3.912h-0.078v3.912l-3.322 -1.209v-3.913l-0.053 -0.058 -0.025 -0.06 -3.336 -1.21v-3.948l0.034 0.013 3.287 1.196 0.015 -0.078 -3.261 -1.187 3.26 -1.187v-0.109L3.876 9.62l-0.307 -0.112 3.26 -1.188v0.877l0.079 -0.055V6.769l3.257 1.185 0.058 -0.061L7.084 6.75l-0.102 -0.037 3.24 -1.179v-0.083L6.854 6.677v0.018l-0.025 0.018v1.523L3.44 9.47v0.02l-0.025 0.017v4.007l-3.39 1.233v0.019L0 14.784v3.995l0.025 0.037 3.4 1.237 0.008 -0.006 0.007 0.01 3.4 1.238 0.008 -0.006 0.006 0.01 3.4 1.237 0.014 -0.009 0.012 0.01 3.45 -1.256 0.026 -0.037 -0.078 -0.027zM3.493 9.563l3.257 1.185 -3.257 1.187V9.562zM3.4 19.96 0.078 18.752v-3.913l2.361 0.86 0.96 0.349v3.913zm0.015 -3.99 -3.08 -1.12 -0.182 -0.066 3.262 -1.187v2.374zm3.399 5.231 -3.321 -1.209V16.08l3.321 1.209v3.912zM23.791 5.434l-3.21 -1.17v2.338zm-3.404 -2.791 -3.24 -1.18 -3.27 1.19 3.247 1.182z" fill="currentColor" stroke-width="1"></path></svg>`,
};

function canonicalUrl(page: string): string {
  const publishedPage =
    publishedDirectory === sourceDirectory
      ? page
      : page.replace(
          `${language}/${sourceDirectory}/`,
          `${language}/${publishedDirectory}/`,
        );
  const pathWithoutExtension = publishedPage.replace(/\.md$/, "");
  const cleanPath = pathWithoutExtension.replace(/(^|\/)index$/, "$1");
  const pathname = cleanPath === "" ? "/" : `/${cleanPath}`;
  return new URL(pathname, siteUrl).toString();
}

function metadataTags(
  title: string,
  description: string,
  url: string,
): HeadConfig[] {
  return [
    ["link", { rel: "canonical", href: url }],
    ["meta", { name: "robots", content: robotsContent }],
    [
      "meta",
      {
        property: "og:type",
        content: url === `${siteUrl}/` ? "website" : "article",
      },
    ],
    ["meta", { property: "og:site_name", content: "Quater" }],
    ["meta", { property: "og:title", content: title }],
    ["meta", { property: "og:description", content: description }],
    ["meta", { property: "og:url", content: url }],
    ["meta", { property: "og:image", content: socialImageUrl }],
    ["meta", { property: "og:image:alt", content: "Quater" }],
    ["meta", { name: "twitter:card", content: "summary" }],
    ["meta", { name: "twitter:title", content: title }],
    ["meta", { name: "twitter:description", content: description }],
    ["meta", { name: "twitter:image", content: socialImageUrl }],
  ];
}

export default defineConfig({
  lang: "en-US",
  title: "Quater",
  description: defaultDescription,
  cleanUrls: true,
  lastUpdated: true,
  outDir: process.env.QUATER_DOCS_OUT_DIR,
  rewrites,
  sitemap: {
    hostname: siteUrl,
  },

  transformHead({ page, title, description }) {
    return metadataTags(
      title,
      description || defaultDescription,
      canonicalUrl(page),
    );
  },

  transformHtml(code) {
    if (publishedDirectory === sourceDirectory) {
      return code;
    }
    // Rewrite only navigation link targets, never literal prose or inline code
    // (e.g. text documenting the "docs/en/dev" source tree or the "/en/dev/"
    // channel). Then restore the version switcher's dev link.
    return code
      .replaceAll(`href="${sourcePrefix}/`, `href="${publishedPrefix}/`)
      .replaceAll(`src="${sourcePrefix}/`, `src="${publishedPrefix}/`)
      .replaceAll(devChannelSentinel, devIndexLink);
  },

  vite: {
    build: {
      chunkSizeWarningLimit: 900,
    },
    plugins: [
      {
        name: "vitepress-search-index-fix",
        enforce: "pre",
        resolveId(id) {
          if (id === "/@localSearchIndex") {
            return id;
          }
        },
      },
    ],
  },

  markdown: {
    config(md) {
      const defaultFence = md.renderer.rules.fence;

      md.renderer.rules.fence = (tokens, index, options, env, self) => {
        const token = tokens[index];
        const language = token.info.trim().split(/\s+/)[0];

        if (language === "mermaid") {
          const code = Buffer.from(token.content, "utf8").toString("base64");
          return `<MermaidDiagram code="${code}" />`;
        }

        if (defaultFence !== undefined) {
          return defaultFence(tokens, index, options, env, self);
        }
        return self.renderToken(tokens, index, options);
      };
    },
  },

  head: [
    ["meta", { name: "theme-color", content: "#ED4B2F" }],
    ["link", { rel: "icon", href: "/logo-no-bg.svg", type: "image/svg+xml" }],
    ["script", { type: "application/ld+json" }, JSON.stringify(structuredData)],
  ],

  themeConfig: {
    logo: { light: "/logo-no-bg.svg", dark: "/logo-no-bg.svg" },
    siteTitle: "Quater",

    nav,

    socialLinks: [
      { icon: "github", link: "https://github.com/DevilsAutumn/quater" },
      { icon: pypiIcon, link: "https://pypi.org/project/quater/" },
    ],

    sidebar: versionSidebars,

    outline: {
      level: [2, 3],
    },

    search: {
      provider: "local",
    },

    footer: {
      message: "Released under the MIT License.",
      copyright: "Copyright © 2026 DevilsAutumn",
    },
  },
});
