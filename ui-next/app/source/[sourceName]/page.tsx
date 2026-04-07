import Link from "next/link";
import { OnboardingWizard } from "../../../components/OnboardingWizard";

type Props = {
  params: Promise<{ sourceName: string }>;
};

export default async function SourcePage({ params }: Props) {
  const { sourceName } = await params;

  return (
    <main className="frame">
      <div style={{ padding: '0 2rem', paddingTop: '1rem', background: 'var(--bg-surface)' }}>
        <Link className="hint" href="/" style={{ textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          ← Back to sources
        </Link>
      </div>

      <OnboardingWizard sourceName={sourceName} />
      
      {/* 
          Note: This is Step 3 (Mock-First). 
          In later phases, we will re-integrate:
          1. loadBundle(sourceName)
          2. loadKnowledgeState(sourceName)
          3. Real-time updates via API 
      */}
    </main>
  );
}
