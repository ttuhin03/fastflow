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
            Overview
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/schnellstart">
            Quick Start
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/setup">
            Setup Guide
          </Link>
          <Link className="button button--secondary button--lg" to="/docs/pipelines/erste-pipeline">
            First Pipeline
          </Link>
        </div>
      </div>
    </header>
  );
}

const ThemenLinks = [
  { to: '/docs/intro', label: 'What is Fast-Flow?', desc: 'Concepts and philosophy' },
  { to: '/docs/setup', label: 'Setup & Configuration', desc: 'Env variables, OAuth, directories' },
  { to: '/docs/pipelines/erste-pipeline', label: 'First Pipeline', desc: 'Tutorial from scratch' },
  { to: '/docs/pipelines/erweiterte-pipelines', label: 'Advanced Pipelines', desc: 'Retries, secrets, scheduling, webhooks' },
  { to: '/docs/architektur', label: 'Architecture', desc: 'Runner cache, container lifecycle' },
  { to: '/docs/troubleshooting', label: 'Troubleshooting', desc: 'Common errors and solutions' },
];

function HomepageThemen() {
  return (
    <section className={styles.themen}>
      <div className="container">
        <Heading as="h2" className="text--center">Documentation</Heading>
        <p className="text--center" style={{ marginBottom: '2rem' }}>
          All topics at a glance – for beginners and advanced users.
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
