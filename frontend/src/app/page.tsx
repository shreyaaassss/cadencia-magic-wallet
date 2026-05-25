'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  FileText, Search, MessageSquare, Lock, PieChart,
  Activity, BarChart3, CheckCircle2, Globe, Heart,
  ArrowRight, CircleDot, CreditCard, DollarSign,
  ShieldCheck, Menu, X,
} from 'lucide-react';
import { ThemeToggle } from '@/components/shared/ThemeToggle';
import './landing.css';

export default function LandingPage() {
  const navRef = useRef<HTMLElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      if (navRef.current) {
        if (window.scrollY > 20) {
          navRef.current.classList.add('scrolled');
        } else {
          navRef.current.classList.remove('scrolled');
        }
      }
    };
    window.addEventListener('scroll', handleScroll, { passive: true });

    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add('visible');
            obs.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    document.querySelectorAll('.reveal').forEach((el) => obs.observe(el));

    return () => {
      window.removeEventListener('scroll', handleScroll);
      obs.disconnect();
    };
  }, []);

  return (
    <>
      {/* NAV */}
      <nav ref={navRef} className="landing-nav">
        <Link href="/" className="nav-logo">
          <div className="nav-logo-mark">
            <CircleDot className="h-3.5 w-3.5" />
          </div>
          <span className="nav-logo-text">Cadencia</span>
        </Link>
        <ul className="nav-links">
          <li><a href="#how">How it works</a></li>
          <li><a href="#features">Features</a></li>
          <li><a href="#blockchain">Settlement</a></li>
          <li><a href="#trust">Customers</a></li>
        </ul>
        <div className="nav-actions">
          <ThemeToggle />
          <Link href="/login" className="btn-ghost">Sign in</Link>
          <div className="nav-register-group">
            <Link href="/register?role=buyer" className="btn-primary-nav">
              I&apos;m a Buyer
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link href="/register?role=seller" className="btn-secondary-nav">
              I&apos;m a Seller
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
        <button
          className="nav-hamburger"
          onClick={() => setMenuOpen(o => !o)}
          aria-label="Toggle menu"
        >
          {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </nav>

      {/* Mobile menu */}
      {menuOpen && (
        <div className="mobile-menu" onClick={() => setMenuOpen(false)}>
          <div className="mobile-menu-inner" onClick={e => e.stopPropagation()}>
            <a href="#how" className="mobile-menu-link" onClick={() => setMenuOpen(false)}>How it works</a>
            <a href="#features" className="mobile-menu-link" onClick={() => setMenuOpen(false)}>Features</a>
            <a href="#blockchain" className="mobile-menu-link" onClick={() => setMenuOpen(false)}>Settlement</a>
            <a href="#trust" className="mobile-menu-link" onClick={() => setMenuOpen(false)}>Customers</a>
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

      {/* HERO — white canvas, clean whitespace */}
      <section className="hero">
        <h1 className="hero-title reveal">
          Trade at the speed of intelligence
        </h1>

        <p className="hero-subtitle reveal reveal-delay-1">
          Cadencia automates the entire B2B procurement cycle — from RFQ to negotiation
          to on-chain settlement — so your team focuses on strategy, not spreadsheets.
        </p>

        <div className="hero-cta reveal reveal-delay-2">
          <Link href="/register?role=buyer" className="btn-cta-primary">
            Get started for free
            <ArrowRight className="h-4 w-4" />
          </Link>
          <Link href="/register?role=seller" className="btn-cta-secondary">
            Book a demo
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>

        <div className="hero-stats reveal reveal-delay-3">
          <div className="hero-stat">
            <span className="hero-stat-value">&#8377;2,400Cr</span>
            <span className="hero-stat-label">Trade volume facilitated</span>
          </div>
          <div className="hero-divider" />
          <div className="hero-stat">
            <span className="hero-stat-value">94%</span>
            <span className="hero-stat-label">Negotiation success rate</span>
          </div>
          <div className="hero-divider" />
          <div className="hero-stat">
            <span className="hero-stat-value">3.2x</span>
            <span className="hero-stat-label">Faster deal closure</span>
          </div>
        </div>
      </section>

      {/* LOGO STRIP */}
      <div className="logo-strip reveal">
        <span className="logo-strip-name">Tata Steel</span>
        <span className="logo-strip-name">JSW Group</span>
        <span className="logo-strip-name">Hindalco</span>
        <span className="logo-strip-name">SAIL</span>
        <span className="logo-strip-name">Ambuja Cements</span>
        <span className="logo-strip-name">Reliance Retail</span>
      </div>

      {/* PREVIEW — app mockup */}
      <div className="preview-section">
        <div className="preview-wrapper reveal">
          <div className="preview-frame">
            <div className="preview-bar">
              <div className="preview-dots">
                <div className="preview-dot" />
                <div className="preview-dot" />
                <div className="preview-dot" />
              </div>
              <div className="preview-url">
                <Lock className="h-2.5 w-2.5" />
                app.cadencia.in/dashboard
              </div>
            </div>
            <div className="preview-body">
              <div className="preview-sidebar">
                <div className="preview-sidebar-logo">
                  <div className="pslm"><CircleDot className="h-2.5 w-2.5" /></div>
                  Cadencia
                </div>
                <div className="pni active"><BarChart3 className="h-3.5 w-3.5" /> Dashboard</div>
                <div className="pni"><Search className="h-3.5 w-3.5" /> Marketplace</div>
                <div className="pni"><MessageSquare className="h-3.5 w-3.5" /> Negotiations</div>
                <div className="pni"><CreditCard className="h-3.5 w-3.5" /> Escrow</div>
                <div className="pni"><BarChart3 className="h-3.5 w-3.5" /> Treasury</div>
                <div className="pni"><FileText className="h-3.5 w-3.5" /> Compliance</div>
              </div>
              <div className="preview-main">
                <div className="preview-header">
                  <div className="preview-heading">Good morning, Arjun</div>
                  <div className="preview-badge">
                    <div className="pbdot" />
                    All systems operational
                  </div>
                </div>
                <div className="preview-cards">
                  <div className="pc">
                    <div className="pc-label">Active RFQs</div>
                    <div className="pc-value">12</div>
                    <div className="pc-sub">+3 new today</div>
                  </div>
                  <div className="pc">
                    <div className="pc-label">Live Sessions</div>
                    <div className="pc-value">7</div>
                    <div className="pc-sub">94% success</div>
                  </div>
                  <div className="pc">
                    <div className="pc-label">Pending Escrow</div>
                    <div className="pc-value">&#8377;2.5Cr</div>
                    <div className="pc-sub">3 contracts</div>
                  </div>
                  <div className="pc">
                    <div className="pc-label">Runway</div>
                    <div className="pc-value">48d</div>
                    <div className="pc-sub" style={{ color: '#d97706' }}>Amber alert</div>
                  </div>
                </div>
                <div className="preview-chart-area">
                  <div className="pcbox">
                    <div className="pct">Price Convergence — #S001</div>
                    <svg className="pcs" viewBox="0 0 240 80" preserveAspectRatio="none">
                      <path d="M0,65 L48,58 L96,50 L144,42 L192,36 L240,30" stroke="var(--ink)" strokeWidth="2" fill="none" />
                      <path d="M0,15 L48,22 L96,32 L144,38 L192,34 L240,30" stroke="#16a34a" strokeWidth="2" fill="none" />
                      <circle cx="240" cy="30" r="4" fill="var(--ink)" opacity=".7" />
                      <text x="155" y="10" fontSize="7" fill="var(--text-muted)" fontFamily="JetBrains Mono,monospace">Converging</text>
                    </svg>
                  </div>
                  <div className="pcbox">
                    <div className="pct">Live Negotiation &middot; Round 5</div>
                    <div className="ptl">
                      <div className="pti">
                        <div className="ptd" style={{ background: 'var(--ink)' }} />
                        <span className="ptt">Buyer Agent</span>
                        <span className="ptp">&#8377;38,000/MT</span>
                      </div>
                      <div className="pti">
                        <div className="ptd" style={{ background: '#16a34a' }} />
                        <span className="ptt">Seller counter</span>
                        <span className="ptp">&#8377;44,500/MT</span>
                      </div>
                      <div className="pti">
                        <div className="ptd" style={{ background: 'var(--ink)' }} />
                        <span className="ptt">Buyer revised</span>
                        <span className="ptp">&#8377;40,200/MT</span>
                      </div>
                      <div className="pti" style={{ opacity: 0.4 }}>
                        <div className="ptd" style={{ background: 'var(--text-muted)' }} />
                        <span className="ptt">Seller responding...</span>
                        <span className="ptp">&middot;&middot;&middot;</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* SIGNATURE CORAL CARD */}
      <div className="signature-coral-band reveal">
        <div className="section-inner">
          <div className="section-eyebrow">AI-native procurement</div>
          <h2 className="section-title">
            Production-grade trade automation at prototype speed
          </h2>
          <p className="section-body">
            From the moment a buyer posts an RFQ to the instant funds settle on-chain,
            Cadencia&apos;s AI agents handle every step — matching, negotiating, and settling
            in real time.
          </p>
          <Link href="/register" className="btn-on-dark">
            Start trading
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </div>

      {/* HOW IT WORKS — white canvas */}
      <section className="landing-section" id="how">
        <div className="section-inner">
          <div className="reveal">
            <div className="section-eyebrow">How it works</div>
            <h2 className="section-title">
              Four steps from requirement to settlement
            </h2>
            <p className="section-body">
              The entire trade lifecycle — automated, compliant, and on-chain. No back-and-forth emails, no manual reconciliation.
            </p>
          </div>
          <div className="steps-grid reveal reveal-delay-2">
            <div className="step">
              <div className="step-number">01 / RFQ</div>
              <div className="step-icon"><FileText className="h-5 w-5" /></div>
              <div className="step-title">Post your requirement</div>
              <p className="step-desc">
                Describe your requirement in plain language. Our AI parses product specs, quantities, budgets, and delivery terms automatically.
              </p>
            </div>
            <div className="step">
              <div className="step-number">02 / MATCH</div>
              <div className="step-icon"><Search className="h-5 w-5" /></div>
              <div className="step-title">AI finds the best sellers</div>
              <p className="step-desc">
                Vector embeddings rank sellers by capability match. You see a scored shortlist — confirm one to begin negotiation.
              </p>
            </div>
            <div className="step">
              <div className="step-number">03 / NEGOTIATE</div>
              <div className="step-icon"><MessageSquare className="h-5 w-5" /></div>
              <div className="step-title">Agents negotiate for you</div>
              <p className="step-desc">
                AI agents exchange offers in real time. You watch the price converge — or step in with a human override anytime.
              </p>
            </div>
            <div className="step">
              <div className="step-number">04 / SETTLE</div>
              <div className="step-icon"><Lock className="h-5 w-5" /></div>
              <div className="step-title">On-chain escrow &amp; compliance</div>
              <p className="step-desc">
                Algorand smart contracts hold funds in escrow. FEMA and GST reports are auto-generated. Settlement is instant.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* CREAM CALLOUT BAND */}
      <div className="cream-band reveal">
        <div className="section-inner" style={{ textAlign: 'center' }}>
          <h2 className="section-title" style={{ maxWidth: '560px', margin: '0 auto 1rem' }}>
            The path to 10x every person in your procurement team
          </h2>
          <p className="section-body" style={{ maxWidth: '440px', margin: '0 auto' }}>
            Stop wasting analyst hours on supplier outreach and price comparison. Let AI agents handle the back-and-forth while your team focuses on strategic decisions.
          </p>
        </div>
      </div>

      {/* FEATURES — white canvas */}
      <section className="landing-section" id="features">
        <div className="section-inner">
          <div className="reveal">
            <div className="section-eyebrow">Platform features</div>
            <h2 className="section-title">Everything a modern trading desk needs</h2>
          </div>
          <div className="features-grid">
            <div className="fc reveal reveal-delay-1">
              <div className="fc-icon"><PieChart className="h-5 w-5" /></div>
              <div className="fc-title">Autonomous AI Negotiations</div>
              <p className="fc-desc">
                Configure your agent&apos;s style — aggressive, balanced, or conservative. Set floor prices and max rounds. The agent works 24/7 so you don&apos;t have to.
              </p>
              <span className="fc-tag">Groq Llama 3.3 70B</span>
            </div>
            <div className="fc reveal reveal-delay-2">
              <div className="fc-icon"><Activity className="h-5 w-5" /></div>
              <div className="fc-title">Live SSE Negotiation Room</div>
              <p className="fc-desc">
                Watch every offer and counter-offer in real time. Price convergence charts update live. Jump in with a human override if the deal needs a personal touch.
              </p>
              <span className="fc-tag">Server-Sent Events</span>
            </div>
            <div className="fc reveal reveal-delay-3">
              <div className="fc-icon"><BarChart3 className="h-5 w-5" /></div>
              <div className="fc-title">Treasury &amp; FX Dashboard</div>
              <p className="fc-desc">
                Multi-currency pool balances across INR, USDC, and ALGO. Live FX exposure, unrealized P&amp;L, and a 30-day liquidity runway forecast.
              </p>
              <span className="fc-tag">Multi-currency</span>
            </div>
            <div className="fc reveal reveal-delay-4">
              <div className="fc-icon"><CheckCircle2 className="h-5 w-5" /></div>
              <div className="fc-title">Compliance Auto-filing</div>
              <p className="fc-desc">
                Every trade generates FEMA and GST reports automatically. Export as PDF or CSV. Audit trails are immutable, timestamped, and verifiable on-chain.
              </p>
              <span className="fc-tag">FEMA &middot; GST &middot; RBI</span>
            </div>
          </div>
        </div>
      </section>

      {/* BLOCKCHAIN — white canvas */}
      <section className="landing-section" id="blockchain">
        <div className="section-inner">
          <div className="blockchain-grid">
            <div className="reveal">
              <div className="section-eyebrow">On-chain settlement</div>
              <h2 className="section-title">Escrow that runs itself</h2>
              <p className="section-body">
                Algorand smart contracts hold buyer funds until delivery is confirmed. No intermediaries. No delays. Fully auditable on a public ledger.
              </p>
              <ul className="bc-list">
                <li className="bc-item">
                  <div className="bc-icon"><Lock className="h-4 w-4" /></div>
                  <div>
                    <div className="bc-title">Atomic group transactions</div>
                    <div className="bc-desc">
                      Fund via Pera Wallet with a single tap. The escrow app call and payment are grouped atomically — either both succeed or neither does.
                    </div>
                  </div>
                </li>
                <li className="bc-item">
                  <div className="bc-icon"><ShieldCheck className="h-4 w-4" /></div>
                  <div>
                    <div className="bc-title">Release, refund, or freeze</div>
                    <div className="bc-desc">
                      Admins can release funds to the seller, refund to buyer, or freeze the escrow pending dispute resolution.
                    </div>
                  </div>
                </li>
                <li className="bc-item">
                  <div className="bc-icon"><Globe className="h-4 w-4" /></div>
                  <div>
                    <div className="bc-title">Cross-border FEMA compliance</div>
                    <div className="bc-desc">
                      Automatic FEMA filings for cross-border trades. Every transaction is linked to a GST-compliant invoice trail.
                    </div>
                  </div>
                </li>
              </ul>
            </div>
            <div className="reveal reveal-delay-2" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <div style={{
                width: 280, height: 280, borderRadius: 'var(--radius-lg)',
                background: 'var(--surface-soft)', border: '1px solid var(--hairline)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 16,
              }}>
                <div style={{
                  width: 64, height: 64, borderRadius: 'var(--radius-lg)',
                  background: 'var(--primary)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: 'var(--on-primary)',
                }}>
                  <Lock className="h-7 w-7" />
                </div>
                <span style={{ fontSize: '.82rem', fontWeight: 500, color: 'var(--ink)' }}>Algorand Escrow</span>
                <span style={{ fontSize: '.72rem', color: 'var(--text-muted)', textAlign: 'center', maxWidth: 200 }}>
                  Smart contract holds funds until both parties confirm delivery
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* DARK CTA CARD */}
      <div className="dark-cta-band reveal">
        <div className="section-eyebrow">Ready to transform procurement?</div>
        <h2 className="section-title">
          Start closing deals intelligently
        </h2>
        <p className="section-body">
          Join 200+ enterprises already using Cadencia. Free to start, no credit card required.
        </p>
        <Link href="/register" className="btn-on-dark">
          Get early access
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      {/* TRUST — surface-soft canvas */}
      <section className="landing-section trust-section" id="trust">
        <div className="section-inner">
          <div className="reveal" style={{ textAlign: 'center' }}>
            <div className="section-eyebrow" style={{ justifyContent: 'center' }}>
              Trusted by India&apos;s industrial enterprises
            </div>
            <h2 className="section-title" style={{ maxWidth: '100%', textAlign: 'center', margin: '0 auto .5rem' }}>
              Powering trade across sectors
            </h2>
          </div>
          <div className="testimonials-grid">
            <div className="tcard reveal reveal-delay-1">
              <div className="tquote">
                &quot;Cadencia closed a &#8377;8Cr steel procurement in 4 hours. Our agents negotiated while our team slept.&quot;
              </div>
              <div className="tauthor">
                <div className="tavatar">RV</div>
                <div>
                  <div className="tname">Rahul Verma</div>
                  <div className="trole">VP Procurement, Tata Steel Ltd</div>
                </div>
              </div>
            </div>
            <div className="tcard reveal reveal-delay-2">
              <div className="tquote">
                &quot;The FEMA compliance automation alone saved us 3 days of paperwork per cross-border deal. Remarkable.&quot;
              </div>
              <div className="tauthor">
                <div className="tavatar">SP</div>
                <div>
                  <div className="tname">Sunita Patel</div>
                  <div className="trole">CFO, Hindalco Industries</div>
                </div>
              </div>
            </div>
            <div className="tcard reveal reveal-delay-3">
              <div className="tquote">
                &quot;The escrow on Algorand gives our finance team full visibility. No more trust issues with new counterparties.&quot;
              </div>
              <div className="tauthor">
                <div className="tavatar">AK</div>
                <div>
                  <div className="tname">Amit Kumar</div>
                  <div className="trole">Head of Trade Finance, JSW Group</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* LIGHT CTA BAND */}
      <div className="light-cta-band reveal">
        <h2 className="section-title">Start building with Cadencia</h2>
        <p className="section-body">
          Sign up in 2 minutes. No credit card required.
        </p>
        <div className="cta-form">
          <input type="email" className="cta-input" placeholder="Enter your work email" />
          <Link href="/register" className="btn-cta-submit">
            Get early access
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
        <p style={{ marginTop: '1rem', fontSize: '.72rem', color: 'var(--text-muted)' }}>
          By signing up, you agree to our Terms of Service and Privacy Policy.
        </p>
      </div>

      {/* FOOTER */}
      <footer className="landing-footer">
        <div className="footer-inner">
          <div className="footer-brand">
            <div className="footer-logo">
              <div className="flm"><CircleDot className="h-3 w-3" /></div>
              Cadencia
            </div>
            <p className="footer-tagline">
              AI-powered B2B trade platform for Indian enterprises. From RFQ to settlement, automated.
            </p>
            <span className="footer-gstin">CIN: U74999MH2024PTC123456</span>
          </div>
          <div>
            <div className="fcol-title">Platform</div>
            <ul className="flinks">
              <li><a href="#">Marketplace</a></li>
              <li><a href="#">AI Negotiations</a></li>
              <li><a href="#">Escrow</a></li>
              <li><a href="#">Treasury</a></li>
              <li><a href="#">Compliance</a></li>
            </ul>
          </div>
          <div>
            <div className="fcol-title">Company</div>
            <ul className="flinks">
              <li><a href="#">About</a></li>
              <li><a href="#">Blog</a></li>
              <li><a href="#">Careers</a></li>
              <li><a href="#">Press kit</a></li>
              <li><a href="#">Contact</a></li>
            </ul>
          </div>
          <div>
            <div className="fcol-title">Legal</div>
            <ul className="flinks">
              <li><a href="#">Privacy Policy</a></li>
              <li><a href="#">Terms of Service</a></li>
              <li><a href="#">Security</a></li>
              <li><a href="#">FEMA Compliance</a></li>
              <li><a href="#">Cookie Policy</a></li>
            </ul>
          </div>
        </div>
        <div className="footer-bottom">
          <span className="fcopy">&copy; 2025 Cadencia Technologies Pvt. Ltd. &middot; Mumbai, Maharashtra &middot; All rights reserved.</span>
          <span className="fmade">
            <Heart className="h-3 w-3" />
            Built on Algorand &middot; Powered by Groq &middot; Made in India
          </span>
        </div>
      </footer>
    </>
  );
}
