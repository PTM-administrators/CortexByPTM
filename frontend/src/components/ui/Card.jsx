// Card generica per le statistiche della dashboard.
export default function Card({ title, value }) {
  return (
    <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-5">
      <div className="text-sm text-slate-500 capitalize">{title.replace(/_/g, " ")}</div>
      <div className="text-2xl font-bold text-slate-800 mt-1">{value}</div>
    </div>
  );
}
