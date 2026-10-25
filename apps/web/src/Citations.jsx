// Numbered citation links for an answer sentence: each id is a chunk the sentence cites.
export default function Citations({ ids, evidence }) {
  return ids.map((id) => {
    const source = evidence.find((e) => e.chunk_id === id);
    const n = evidence.indexOf(source) + 1;
    return (
      <a key={id} className="chip" href={source?.source_url} target="_blank" rel="noreferrer"
         title={source ? `${source.title} — ${source.section}` : id}>
        [{n || "?"}]
      </a>
    );
  });
}
