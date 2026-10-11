export default function ConflictComparison({ version, latest, draft, reapply }: {
  version: number; latest: Record<string, string>; draft: Record<string, string>; reapply: () => void;
}) {
  return <section className="conflict-comparison" aria-label="Compare conflicting changes">
    <h3>Compare with saved version {version}</h3>
    <p>Your draft is still in the form. Reapply it against this version, review your edits, then save. Saving replaces the compared values with your form values. Any newer changes will be checked again.</p>
    <div className="conflict-columns"><div><h4>Latest saved values</h4>{Object.entries(latest).map(([key, value]) => <div key={key}><strong>{key}</strong><pre>{value || '(empty)'}</pre></div>)}</div>
      <div><h4>Your draft when saving</h4>{Object.entries(draft).map(([key, value]) => <div key={key}><strong>{key}</strong><pre>{value || '(empty)'}</pre></div>)}</div></div>
    <button type="button" className="button secondary" onClick={reapply}>Reapply my draft</button>
  </section>
}
