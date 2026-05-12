import { readdirSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitepress'
import type { DefaultTheme } from 'vitepress'

type DocsVersion = {
  label: string
  directory: string
  base: string
  index: string
}

const language = 'en'
const latestDirectory = 'latest'
const docsRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const versionRoot = path.join(docsRoot, language)

function compareReleaseVersions(left: string, right: string): number {
  const leftParts = left.split('-')[0]?.split('.').map(Number) ?? []
  const rightParts = right.split('-')[0]?.split('.').map(Number) ?? []

  for (let index = 0; index < 3; index += 1) {
    const diff = (rightParts[index] ?? 0) - (leftParts[index] ?? 0)
    if (diff !== 0) {
      return diff
    }
  }

  return right.localeCompare(left)
}

function readDocsVersions(): DocsVersion[] {
  const releases = readdirSync(versionRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name !== latestDirectory)
    .map((entry) => entry.name)
    .sort(compareReleaseVersions)

  return [
    {
      label: 'Latest',
      directory: latestDirectory,
      base: `/${language}/${latestDirectory}/`,
      index: `/${language}/${latestDirectory}/index`,
    },
    ...releases.map((release) => ({
      label: release,
      directory: release,
      base: `/${language}/${release}/`,
      index: `/${language}/${release}/index`,
    })),
  ]
}

function sidebarFor(version: DocsVersion): DefaultTheme.SidebarItem[] {
  return [
    {
      text: version.label,
      items: [
        { text: 'Overview', link: version.index },
        { text: 'Quickstart', link: `${version.base}quickstart` },
        { text: 'Actions and CLI', link: `${version.base}actions` },
        { text: 'Testing', link: `${version.base}testing` },
        { text: 'Public API', link: `${version.base}api` },
        { text: 'MCP', link: `${version.base}mcp` },
        { text: 'Security', link: `${version.base}security` },
      ],
    },
  ]
}

const docsVersions = readDocsVersions()
const latestDocs = docsVersions[0]
const versionSidebars = Object.fromEntries(
  docsVersions.map((version) => [version.base, sidebarFor(version)]),
) as DefaultTheme.SidebarMulti

const versionItems = docsVersions.map((version) => ({
  text: version.label,
  link: version.index,
}))

const latestBase = latestDocs?.base ?? `/${language}/${latestDirectory}/`

const nav: DefaultTheme.NavItem[] = [
  { text: 'Guide', link: `${latestBase}quickstart` },
  { text: 'CLI', link: `${latestBase}actions` },
  { text: 'API', link: `${latestBase}api` },
  { text: 'MCP', link: `${latestBase}mcp` },
  {
    text: 'Version',
    items: versionItems,
  },
]

export default defineConfig({
  lang: 'en-US',
  title: 'Quater',
  description: 'Typed Python APIs for humans and agents.',
  cleanUrls: true,
  lastUpdated: true,

  vite: {
    build: {
      chunkSizeWarningLimit: 900,
    },
    plugins: [
      {
        name: 'vitepress-search-index-fix',
        enforce: 'pre',
        resolveId(id) {
          if (id === '/@localSearchIndex') {
            return id
          }
        },
      },
    ],
  },

  markdown: {
    config(md) {
      const defaultFence = md.renderer.rules.fence

      md.renderer.rules.fence = (tokens, index, options, env, self) => {
        const token = tokens[index]
        const language = token.info.trim().split(/\s+/)[0]

        if (language === 'mermaid') {
          const code = Buffer.from(token.content, 'utf8').toString('base64')
          return `<MermaidDiagram code="${code}" />`
        }

        if (defaultFence !== undefined) {
          return defaultFence(tokens, index, options, env, self)
        }
        return self.renderToken(tokens, index, options)
      }
    },
  },

  head: [
    ['meta', { name: 'theme-color', content: '#ED4B2F' }],
    ['link', { rel: 'icon', href: '/logo-no-bg.svg', type: 'image/svg+xml' }],
  ],

  themeConfig: {
    logo: { light: '/logo-white-bg.svg', dark: '/logo-black-bg.svg' },
    siteTitle: 'Quater',

    nav,

    sidebar: versionSidebars,

    outline: {
      level: [2, 3],
    },

    search: {
      provider: 'local',
    },

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2026 Bhuvnesh Sharma',
    },
  },
})
