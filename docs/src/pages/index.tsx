import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import HomepageFeatures from '@site/src/components/HomepageFeatures';
import Heading from '@theme/Heading';

import styles from './index.module.css';

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={clsx('hero hero--primary', styles.heroBanner)}>
      <div className="container">
        <Heading as="h1" className="hero__title">
          {siteConfig.title}
        </Heading>
        <p className="hero__subtitle">{siteConfig.tagline}</p>
        <div className={styles.buttons}>
          <Link className="button button--secondary button--lg" to="/docs/intro">
            Übersicht
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/schnellstart">
            Schnellstart
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/setup">
            Setup-Anleitung
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/pipelines/erste-pipeline">
            Erste Pipeline
          </Link>
        </div>
      </div>
    </header>
  );
}

const ThemenLinks = [
  { to: '/docs/intro', label: 'Was ist Fast-Flow?', desc: 'Konzepte und Philosophie' },
  { to: '/docs/setup', label: 'Setup & Konfiguration', desc: 'Env-Variablen, OAuth, Verzeichnisse' },
  { to: '/docs/pipelines/erste-pipeline', label: 'Erste Pipeline', desc: 'Tutorial von Null an' },
  { to: '/docs/pipelines/erweiterte-pipelines', label: 'Erweiterte Pipelines', desc: 'Retries, Secrets, Scheduling, Webhooks' },
  { to: '/docs/architektur', label: 'Architektur', desc: 'Runner-Cache, Container-Lifecycle' },
  { to: '/docs/troubleshooting', label: 'Troubleshooting', desc: 'Häufige Fehler und Lösungen' },
];

function HomepageThemen() {
  return (
    <section className={styles.themen}>
      <div className="container">
        <Heading as="h2" className="text--center">Dokumentation</Heading>
        <p className="text--center" style={{ marginBottom: '2rem' }}>
          Alle Themen im Überblick – für Einsteiger und Fortgeschrittene.
        </p>
        <div className="row">
          {ThemenLinks.map(({ to, label, desc }) => (
            <div key={to} className="col col--4 margin-bottom--lg">
              <Link to={to} className={styles.themenCard}>
                <strong>{label}</strong>
                <span className="text--muted">{desc}</span>
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function Home(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout title={siteConfig.title} description={siteConfig.tagline}>
      <HomepageHeader />
      <main>
        <HomepageFeatures />
        <HomepageThemen />
      </main>
    </Layout>
  );
}
