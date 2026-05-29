'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import {
  ArrowRight, Check, CircleDot, Menu, X,
} from 'lucide-react';
import { ThemeToggle } from '@/components/shared/ThemeToggle';
import { LandingFooter } from '@/components/shared/LandingFooter';
import './pricing.css';

const PLANS = [
  {
    id: 'free',
    role: 'Buyer',
    name: 'Free',
    desc: 'Try the platform risk-free. No card needed.',
    monthly: null,
    yearly: null,
    highlight: false,
    badge: null,
    cta: 'Get started free',
    href: '/register?role=buyer',
    features: [
      'Unlimited RFQ postings',
      '1 AI negotiation session / month',
      '1 complete transaction / month',
      'Marketplace access',
      'Basic deal dashboard',
    ],
  },
  {
    id: 'pro',
    role: 'Buyer',
    name: 'Pro',
    desc: 'Unlimited automation for procurement teams.',
    monthly: 5.99,
    yearly: 57.99,
    highlight: true,
    badge: 'Most popular',
    cta: 'Start Pro',
    href: '/register?role=buyer&plan=pro',
    features: [
      'Everything in Free',
      'Unlimited AI negotiation sessions',
      'Unlimited transactions',
      'FEMA & GST auto-reports',
      'Treasury & FX dashboard',
      'Algorand escrow access',
      'Priority AI supplier matching',
    ],
  },
  {
    id: 'seller',
    role: 'Seller',
    name: 'Seller',
    desc: 'List, bid, and close deals on the platform.',
    monthly: 9.99,
    yearly: 95.99,
    highlight: false,
    badge: null,
    cta: 'Join as Seller',
    href: '/register?role=seller',
    features: [
      'Marketplace listing & visibility',
      'Unlimited RFQ responses',
      'AI-assisted bid generation',
      'Seller analytics dashboard',
      'Priority placement in results',
      'Deal history & insights',
      'Escrow & settlement access',
    ],
  },
];

const FAQS = [
  {
    q: 'Can I upgrade or downgrade anytime?',
    a: 'Yes. Switch plans anytime from your account settings. Changes take effect on the next billing cycle.',
  },
  {
    q: 'How does the Free tier work?',
    a: 'Free is permanent — not a trial. You get unlimited RFQ postings and one full negotiation session + transaction per month, forever.',
  },
  {
    q: 'What currency is billing in?',
    a: 'All plans are billed in USD. Invoices are available from your billing dashboard.',
  },
  {
    q: 'Is there a setup fee?',
    a: 'No setup fees, no hidden charges. Pay only the listed monthly or annual rate.',
  },
];

export default function PricingPage() {
  const navRef = useRef<HTMLElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [yearly, setYearly] = useState(false);
  const orbRef1 = useRef<HTMLDivElement>(null);
  const orbRef2 = useRef<HTMLDivElement>(null);
  const orbRef3 = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Nav scroll
    const handleScroll = () => {
      if (navRef.current) {
        navRef.current.classList.toggle('scrolled', window.scrollY > 20);
      }
      // Parallax orbs
      const y = window.scrollY;
      if (orbRef1.current) orbRef1.current.style.transform = `translateY(${y * 0.18}px)`;
      if (orbRef2.current) orbRef2.current.style.transform = `translateY(${y * -0.12}px)`;
      if (orbRef3.current) orbRef3.current.style.transform = `translateY(${y * 0.08}px)`;
    };
    window.addEventListener('scroll', handleScroll, { passive: true });

    // Reveal on scroll
    const obs = new IntersectionObserver(
      (entries) => entries.forEach((e) => {
        if (e.isIntersecting) { e.target.classList.add('visible'); obs.unobserve(e.target); }
      }),
      { threshold: 0.1 }
    );
    document.querySelectorAll('.reveal').forEach((el) => obs.observe(el));

    return () => { window.removeEventListener('scroll', handleScroll); obs.disconnect(); };
  }, []);

  return (
    <>
      {/* NAV */}
      <nav ref={navRef} className="landing-nav">
        <Link href="/" className="nav-logo">
          <Image src="/cadencia-logo.png" alt="Cadencia" width={40} height={40} className="nav-logo-img" />
        </Link>
        <ul className="nav-links">
          <li><Link href="/#how">How it works</Link></li>
          <li><Link href="/#features">Features</Link></li>
          <li><Link href="/#blockchain">Settlement</Link></li>
          <li><Link href="/pricing" style={{ color: 'var(--ink)', fontWeight: 500 }}>Pricing</Link></li>
        </ul>
        <div className="nav-actions">
          <ThemeToggle />
          <Link href="/login" className="btn-ghost">Sign in</Link>
          <div className="nav-register-group">
            <Link href="/register?role=buyer" className="btn-primary-nav">
              I&apos;m a Buyer <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link href="/register?role=seller" className="btn-secondary-nav">
              I&apos;m a Seller <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
        <button className="nav-hamburger" onClick={() => setMenuOpen(o => !o)} aria-label="Toggle menu">
          {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </nav>

      {/* Mobile menu */}
      {menuOpen && (
        <div className="mobile-menu" onClick={() => setMenuOpen(false)}>
          <div className="mobile-menu-inner" onClick={e => e.stopPropagation()}>
            <Link href="/#how" className="mobile-menu-link" onClick={() => setMenuOpen(false)}>How it works</Link>
            <Link href="/#features" className="mobile-menu-link" onClick={() => setMenuOpen(false)}>Features</Link>
            <Link href="/#blockchain" className="mobile-menu-link" onClick={() => setMenuOpen(false)}>Settlement</Link>
            <Link href="/pricing" className="mobile-menu-link" onClick={() => setMenuOpen(false)}>Pricing</Link>
            <div className="mobile-menu-divider" />
            <Link href="/login" className="mobile-menu-link" onClick={() => setMenuOpen(false)}>Sign in</Link>
            <Link href="/register?role=buyer" className="btn-primary-nav w-full justify-center" onClick={() => setMenuOpen(false)}>
              I&apos;m a Buyer <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link href="/register?role=seller" className="btn-secondary-nav w-full justify-center" onClick={() => setMenuOpen(false)}>
              I&apos;m a Seller <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      )}

      {/* BACKGROUND ORBS — parallax */}
      <div className="pricing-orbs" aria-hidden="true">
        <div className="pricing-orb pricing-orb-1" ref={orbRef1} />
        <div className="pricing-orb pricing-orb-2" ref={orbRef2} />
        <div className="pricing-orb pricing-orb-3" ref={orbRef3} />
      </div>

      {/* HERO */}
      <section className="pricing-hero">
        <div className="reveal">
          <div className="section-eyebrow" style={{ justifyContent: 'center' }}>Pricing</div>
          <h1 className="pricing-hero-title">Simple, transparent pricing</h1>
          <p className="pricing-hero-sub">
            Start free. Upgrade when you need more. No contracts, cancel anytime.
          </p>
        </div>

        {/* Billing toggle */}
        <div className="billing-toggle reveal reveal-delay-1">
          <button
            className={`toggle-option${!yearly ? ' active' : ''}`}
            onClick={() => setYearly(false)}
          >
            Monthly
          </button>
          <button
            className={`toggle-option${yearly ? ' active' : ''}`}
            onClick={() => setYearly(true)}
          >
            Yearly
          </button>
          <span className="toggle-save-badge">Save ~20%</span>
        </div>
      </section>

      {/* PRICING CARDS */}
      <div className="pricing-cards-wrap">
        <div className="pricing-cards">
          {PLANS.map((plan, i) => (
            <div
              key={plan.id}
              className={`pricing-card reveal${plan.highlight ? ' highlighted' : ''}${
                i === 0 ? ' float-a' : i === 1 ? ' float-b' : ' float-c'
              }`}
              style={{ transitionDelay: `${i * 0.1}s` }}
            >
              {plan.badge && <div className="plan-badge">{plan.badge}</div>}

              <div className="plan-role-tag">{plan.role}</div>
              <div className="plan-name">{plan.name}</div>
              <p className="plan-desc">{plan.desc}</p>

              <div className="plan-price">
                {plan.monthly === null ? (
                  <span className="plan-price-amount">Free</span>
                ) : (
                  <>
                    <span className="plan-price-currency">$</span>
                    <span className="plan-price-amount">
                      {yearly
                        ? (plan.yearly! / 12).toFixed(2)
                        : plan.monthly.toFixed(2)}
                    </span>
                    <span className="plan-price-period">/ mo</span>
                  </>
                )}
              </div>

              <p className="plan-price-subtext">
                {plan.monthly === null
                  ? 'Always free'
                  : yearly
                  ? `$${plan.yearly!} billed annually · save ~20%`
                  : 'Billed monthly · cancel anytime'}
              </p>

              <div className="plan-divider" />

              <ul className="plan-features">
                {plan.features.map((f) => (
                  <li key={f} className="plan-feature">
                    <span className="plan-feature-check">
                      <Check className="h-2.5 w-2.5" strokeWidth={3} />
                    </span>
                    {f}
                  </li>
                ))}
              </ul>

              <Link
                href={plan.href}
                className={`plan-cta${plan.highlight ? ' primary' : ''}`}
              >
                {plan.cta}
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          ))}
        </div>
      </div>

      {/* FAQ */}
      <section className="pricing-faq reveal">
        <h2 className="faq-title">Common questions</h2>
        {FAQS.map((item) => (
          <div key={item.q} className="faq-item">
            <div className="faq-q">{item.q}</div>
            <div className="faq-a">{item.a}</div>
          </div>
        ))}
      </section>

      {/* FOOTER */}
      <LandingFooter />
    </>
  );
}
