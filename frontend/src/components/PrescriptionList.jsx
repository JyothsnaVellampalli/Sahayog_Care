export default function PrescriptionList({ items = [] }) {
  if (!items.length) return <p>No medicines prescribed.</p>;
  return <ul>{items.map((item, index) => <li key={item.brand_id || index}>
    <strong>{item.brand} · {item.strength_form}</strong>
    <p>{item.dose} · {item.frequency} · {item.duration}</p>
    {item.quantity != null && <p>Quantity: {item.quantity} stock units</p>}
    {item.instructions && <p>{item.instructions}</p>}
  </li>)}</ul>;
}
