import Image from 'next/image';

const DEVS = [
  { initials: 'SD', name: 'Shreyas Dhumal',       url: 'https://www.linkedin.com/in/shreyas-dhumal-21074a1b1' },
  { initials: 'AW', name: 'Aditya Wagh',           url: 'https://www.linkedin.com/in/adityawaghcse' },
  { initials: 'HM', name: 'Harsh Mogalgiddikar',   url: 'https://www.linkedin.com/in/harsh-mogalgiddikar' },
  { initials: 'SC', name: 'Samiksha Chaudhari',    url: 'https://www.linkedin.com/in/samiksha-chaudhai' },
];

export function LandingFooter() {
  return (
    <footer className="lfc">
      <div className="lfc-inner">
        {/* Brand + contact */}
        <div className="lfc-brand">
          <Image src="/logo-light.png" alt="Cadencia" width={52} height={52} className="lfc-logo-img logo-for-light" />
          <Image src="/logo-dark.png"  alt="Cadencia" width={52} height={52} className="lfc-logo-img logo-for-dark" />
          <p className="lfc-tagline">
            AI-powered B2B trade platform.<br />
            From RFQ to settlement, automated.
          </p>
          <a href="mailto:contact.cadencia@gmail.com" className="lfc-email">
            contact.cadencia@gmail.com
          </a>
        </div>

        {/* Team */}
        <div className="lfc-team">
          <div className="lfc-team-label">Built by</div>
          <div className="lfc-devs">
            {DEVS.map((dev) => (
              <a
                key={dev.url}
                href={dev.url}
                target="_blank"
                rel="noopener noreferrer"
                className="lfc-dev"
              >
                <div className="lfc-dev-avatar">{dev.initials}</div>
                <div className="lfc-dev-name">{dev.name}</div>
              </a>
            ))}
          </div>
        </div>
      </div>

      <div className="lfc-bottom">
        <span>&copy; 2025 Cadencia Technologies &middot; Made in India</span>
      </div>
    </footer>
  );
}
