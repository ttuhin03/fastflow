import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'Fast-Flow',
  tagline: 'Der schlanke, Docker-native, Python-zentrische Task-Orchestrator',
  favicon: 'img/favicon.ico',

  markdown: {
    mermaid: true,
  },

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  url: 'https://ttuhin03.github.io',
  baseUrl: '/',

  organizationName: 'ttuhin03',
  projectName: 'fastflow',

  onBrokenLinks: 'throw',

  i18n: {
    defaultLocale: 'de',
    locales: ['de'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/ttuhin03/fastflow/tree/main/docs/',
        },
        blog: false, // erstmal deaktiviert
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themes: [
    '@docusaurus/theme-mermaid',
    [
      require.resolve('@easyops-cn/docusaurus-search-local'),
      {
        hashed: true,
        language: ['de'],
        indexDocs: true,
        indexBlog: false,
      },
    ],
  ],

  themeConfig: {
    image: 'img/fastflow_banner.png',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Fast-Flow',
      logo: {
        alt: 'Fast-Flow Logo',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'tutorialSidebar',
          position: 'left',
          label: 'Doku',
        },
        {
          href: 'https://github.com/ttuhin03/fastflow',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Doku',
          items: [
            {label: 'Intro', to: '/docs/intro'},
            {label: 'Schnellstart', to: '/docs/schnellstart'},
            {label: 'Setup', to: '/docs/setup'},
            {label: 'Erste Pipeline', to: '/docs/pipelines/erste-pipeline'},
            {label: 'Troubleshooting', to: '/docs/troubleshooting'},
          ],
        },
        {
          title: 'Mehr',
          items: [
            {label: 'GitHub', href: 'https://github.com/ttuhin03/fastflow'},
            {label: 'Disclaimer', to: '/docs/disclaimer'},
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Fast-Flow. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
    mermaid: {
      theme: { light: 'neutral', dark: 'dark' },
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
