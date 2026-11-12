import { SITE } from "./site";
import { goSection } from "./Landing";

export default function Footer() {
  const { email, linkedin, github } = SITE.contact;
  const go = (id: string) => (e: React.MouseEvent) => { e.preventDefault(); goSection(id); };
  return (
    <footer className="footer">
      <div className="footer-inner">
        <div className="footer-brand">
          <b>{SITE.product}</b>
          <p>{SITE.context}</p>
        </div>
        <nav aria-label="Product">
          <h3>Product</h3>
          <a href="#/run">Try it</a>
          <a href="#/history">History</a>
          <a href="#/settings">Rule settings</a>
        </nav>
        <nav aria-label="Learn">
          <h3>How it works</h3>
          <a href="#how" onClick={go("how")}>The nine steps</a>
          <a href="#cases" onClick={go("cases")}>Hard cases</a>
          <a href="#principle" onClick={go("principle")}>Reading vs deciding</a>
        </nav>
        <nav aria-label="Contact">
          <h3>Contact</h3>
          <a href="#contact" onClick={go("contact")}>Send a message</a>
          {email && <a href={`mailto:${email}`}>{email}</a>}
          {linkedin && <a href={linkedin} target="_blank" rel="noreferrer">LinkedIn</a>}
          {github && <a href={github} target="_blank" rel="noreferrer">GitHub</a>}
        </nav>
      </div>
      <p className="footer-base">
        Built by {SITE.author}, November 2026.
      </p>
    </footer>
  );
}
